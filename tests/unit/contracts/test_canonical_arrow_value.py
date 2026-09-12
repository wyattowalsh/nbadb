from __future__ import annotations

import copy
import json
import math
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, cast
from zoneinfo import ZoneInfo

import polars as pl
import pyarrow as pa
import pytest

import nbadb.contracts.canonical_arrow_value as codec
from nbadb.contracts.canonical_arrow_value import (
    ArrowLogicalTypeV1,
    CanonicalArrowValueError,
    CanonicalArrowValueV1,
    ValueBudget,
    ValueBudgetLimits,
    canonical_arrow_array_scalar,
    canonical_arrow_scalar,
    canonical_arrow_type,
    checked_add,
    checked_product,
    compare_canonical_arrow_values,
    decode_canonical_arrow_value,
)
from nbadb.schemas.registry import (
    _raw_schema_registry,
    _staging_schema_registry,
    _star_schema_registry,
)


def _fixed_width_array(dtype: pa.DataType, raw_little_endian: bytes) -> pa.Array:
    return pa.Array.from_buffers(dtype, 1, [None, pa.py_buffer(raw_little_endian)])


def _float_array(dtype: pa.DataType, bits: str) -> pa.Array:
    return _fixed_width_array(dtype, bytes.fromhex(bits)[::-1])


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


@pytest.mark.parametrize(
    "dtype",
    [
        pa.null(),
        pa.bool_(),
        pa.int8(),
        pa.int16(),
        pa.int32(),
        pa.int64(),
        pa.uint8(),
        pa.uint16(),
        pa.uint32(),
        pa.uint64(),
        pa.float16(),
        pa.float32(),
        pa.float64(),
        pa.decimal128(38, 2),
        pa.decimal256(50, 4),
        pa.string(),
        pa.large_string(),
        pa.binary(),
        pa.large_binary(),
        pa.binary(3),
        pa.date32(),
        pa.date64(),
        pa.timestamp("s"),
        pa.timestamp("ms", tz="UTC"),
        pa.timestamp("us", tz="America/New_York"),
        pa.timestamp("ns", tz="UTC"),
        pa.time32("s"),
        pa.time32("ms"),
        pa.time64("us"),
        pa.time64("ns"),
        pa.duration("s"),
        pa.duration("ms"),
        pa.duration("us"),
        pa.duration("ns"),
        pa.list_(pa.field("item", pa.int64(), nullable=True)),
        pa.large_list(pa.field("element", pa.string(), nullable=False)),
        pa.list_view(pa.field("item", pa.int32(), nullable=True)),
        pa.large_list_view(pa.field("item", pa.int32(), nullable=True)),
        pa.list_(pa.field("item", pa.int64(), nullable=True), 2),
        pa.struct(
            [
                pa.field("label", pa.string(), nullable=True),
                pa.field("score", pa.decimal128(10, 2), nullable=False),
            ]
        ),
        pa.dictionary(pa.uint8(), pa.large_string(), ordered=False),
        pa.dictionary(pa.uint8(), pa.large_string(), ordered=True),
    ],
)
def test_logical_type_descriptor_round_trips_exact_arrow_type(dtype: pa.DataType) -> None:
    logical_type = canonical_arrow_type(dtype)
    parsed = ArrowLogicalTypeV1.from_canonical_bytes(logical_type.to_canonical_bytes())

    assert parsed == logical_type
    assert parsed.type_sha256 == logical_type.type_sha256
    assert parsed.to_arrow_type().equals(dtype)


@pytest.mark.parametrize(
    ("dtype", "values"),
    [
        (pa.int8(), (-128, 0, 127)),
        (pa.int16(), (-(2**15), 0, 2**15 - 1)),
        (pa.int32(), (-(2**31), 0, 2**31 - 1)),
        (pa.int64(), (-(2**63), 0, 2**63 - 1)),
        (pa.uint8(), (0, 2**8 - 1)),
        (pa.uint16(), (0, 2**16 - 1)),
        (pa.uint32(), (0, 2**32 - 1)),
        (pa.uint64(), (0, 2**64 - 1)),
    ],
)
def test_all_integer_widths_preserve_exact_bounds(
    dtype: pa.DataType,
    values: tuple[int, ...],
) -> None:
    for value in values:
        receipt = canonical_arrow_scalar(value, dtype)
        assert receipt.value_payload() == {"tag": "integer", "value": str(value)}
        assert decode_canonical_arrow_value(receipt) == value
        assert CanonicalArrowValueV1.from_canonical_bytes(receipt.to_canonical_bytes()) == receipt


@pytest.mark.parametrize(
    ("dtype", "bits"),
    [
        (pa.float16(), "0000"),
        (pa.float16(), "8000"),
        (pa.float16(), "0001"),
        (pa.float16(), "7c00"),
        (pa.float16(), "fc00"),
        (pa.float16(), "7e01"),
        (pa.float32(), "00000000"),
        (pa.float32(), "80000000"),
        (pa.float32(), "00000001"),
        (pa.float32(), "7f800000"),
        (pa.float32(), "ff800000"),
        (pa.float32(), "7fc00001"),
        (pa.float32(), "ffc12345"),
        (pa.float64(), "0000000000000000"),
        (pa.float64(), "8000000000000000"),
        (pa.float64(), "0000000000000001"),
        (pa.float64(), "7ff0000000000000"),
        (pa.float64(), "fff0000000000000"),
        (pa.float64(), "7ff8000000000001"),
        (pa.float64(), "fff8abcdef012345"),
    ],
)
def test_float_bits_preserve_zero_nonfinite_subnormal_and_nan_payloads(
    dtype: pa.DataType,
    bits: str,
) -> None:
    receipt = canonical_arrow_array_scalar(_float_array(dtype, bits), 0)

    assert receipt.value_payload() == {"tag": "float", "bits": bits}
    parsed = CanonicalArrowValueV1.from_canonical_bytes(receipt.to_canonical_bytes())
    assert parsed.value_payload()["bits"] == bits


def test_signed_zero_and_nan_payloads_do_not_alias() -> None:
    positive_zero = canonical_arrow_array_scalar(_float_array(pa.float64(), "0000000000000000"), 0)
    negative_zero = canonical_arrow_array_scalar(_float_array(pa.float64(), "8000000000000000"), 0)
    first_nan = canonical_arrow_array_scalar(_float_array(pa.float64(), "7ff8000000000001"), 0)
    second_nan = canonical_arrow_array_scalar(_float_array(pa.float64(), "7ff8000000000002"), 0)

    assert not compare_canonical_arrow_values(positive_zero, negative_zero)
    assert not compare_canonical_arrow_values(first_nan, second_nan)
    decoded_nan = decode_canonical_arrow_value(first_nan)
    assert isinstance(decoded_nan, float)
    assert math.isnan(decoded_nan)


@pytest.mark.parametrize(
    ("dtype", "value", "unscaled"),
    [
        (pa.decimal128(10, 2), Decimal("1.20"), "120"),
        (
            pa.decimal128(38, 2),
            Decimal("-999999999999999999999999999999999999.99"),
            "-99999999999999999999999999999999999999",
        ),
        (pa.decimal256(50, 4), Decimal("0.0000"), "0"),
        (pa.decimal128(10, -2), Decimal("1.20E+3"), "12"),
    ],
)
def test_decimal_uses_exact_unscaled_integer(
    dtype: pa.DataType,
    value: Decimal,
    unscaled: str,
) -> None:
    receipt = canonical_arrow_scalar(value, dtype)

    assert receipt.value_payload() == {"tag": "decimal", "unscaled": unscaled}
    assert decode_canonical_arrow_value(receipt) == value


def test_utf8_and_binary_preserve_empty_unicode_and_all_byte_values() -> None:
    unicode_value = "NBA 🏀 e\u0301"
    raw = bytes(range(256))
    text_receipt = canonical_arrow_scalar(unicode_value, pa.large_string())
    empty_receipt = canonical_arrow_scalar("", pa.string())
    binary_receipt = canonical_arrow_scalar(raw, pa.binary())
    fixed_receipt = canonical_arrow_scalar(b"\x00\xff", pa.binary(2))

    assert decode_canonical_arrow_value(text_receipt) == unicode_value
    assert decode_canonical_arrow_value(empty_receipt) == ""
    assert binary_receipt.value_payload() == {
        "tag": "binary",
        "byte_length": 256,
        "hex": raw.hex(),
    }
    assert decode_canonical_arrow_value(fixed_receipt) == b"\x00\xff"


@pytest.mark.parametrize(
    ("dtype", "value"),
    [
        (pa.date32(), date(2026, 8, 27)),
        (pa.date64(), date(2026, 8, 27)),
        (pa.timestamp("s"), datetime(2026, 8, 27, 12, 0)),
        (pa.timestamp("ms", tz="UTC"), datetime(2026, 8, 27, 12, 0, tzinfo=UTC)),
        (
            pa.timestamp("us", tz="America/New_York"),
            datetime(2026, 8, 27, 12, 0, tzinfo=ZoneInfo("America/New_York")),
        ),
        (pa.time32("s"), time(12, 34, 56)),
        (pa.time32("ms"), time(12, 34, 56, 123000)),
        (pa.time64("us"), time(12, 34, 56, 123456)),
        (pa.duration("s"), timedelta(seconds=-2)),
        (pa.duration("us"), timedelta(seconds=1, microseconds=2)),
    ],
)
def test_python_temporal_values_preserve_exact_arrow_units(
    dtype: pa.DataType,
    value: object,
) -> None:
    receipt = canonical_arrow_scalar(value, dtype)

    assert receipt.tag in {"date", "timestamp", "time", "duration"}
    assert receipt.logical_type.to_arrow_type().equals(dtype)
    assert decode_canonical_arrow_value(receipt) == value


def test_aware_timestamp_is_independent_of_runtime_pyarrow_conversion_shims() -> None:
    # Importing Pandera installs compatibility behavior in the same process.
    # The canonical codec must still derive the UTC instant, not local wall time.
    __import__("pandera")
    dtype = pa.timestamp("us", tz="America/New_York")
    value = datetime(2026, 8, 27, 12, 0, tzinfo=ZoneInfo("America/New_York"))

    receipt = canonical_arrow_scalar(value, dtype)

    assert receipt.value_payload() == {
        "tag": "timestamp",
        "ticks": "1787846400000000",
    }
    assert decode_canonical_arrow_value(receipt) == value


def test_every_concrete_repo_schema_dtype_belongs_to_the_closed_codec_set() -> None:
    registries = (
        _raw_schema_registry(),
        _staging_schema_registry(),
        _star_schema_registry(),
    )
    concrete_columns = 0

    for registry in registries:
        for schema in registry.values():
            for column in schema.to_schema().columns.values():
                if column.dtype is None:
                    # An untyped model column has no declared dtype to admit;
                    # committed frames still arrive with a concrete Arrow type.
                    continue
                arrow_type = (
                    pl.Series(
                        "value",
                        [],
                        dtype=column.dtype.type,
                    )
                    .to_arrow()
                    .type
                )
                descriptor = canonical_arrow_type(arrow_type)
                assert descriptor.to_arrow_type().equals(arrow_type)
                concrete_columns += 1

    assert concrete_columns > 0


@pytest.mark.parametrize(
    ("dtype", "ticks"),
    [
        (pa.timestamp("ns", tz="UTC"), 1),
        (pa.timestamp("ns", tz="UTC"), -1),
        (pa.time64("ns"), 1),
        (pa.time64("ns"), 86_400_000_000_000 - 1),
        (pa.duration("ns"), 1),
        (pa.duration("ns"), -1),
    ],
)
def test_nanosecond_temporal_ticks_do_not_route_through_python_microseconds(
    dtype: pa.DataType,
    ticks: int,
) -> None:
    raw = ticks.to_bytes(8, byteorder="little", signed=True)
    receipt = canonical_arrow_array_scalar(_fixed_width_array(dtype, raw), 0)

    assert receipt.value_payload() == {"tag": receipt.tag, "ticks": str(ticks)}


def test_nested_null_empty_list_fixed_list_and_ordered_struct_are_distinct() -> None:
    nested_type = pa.struct(
        [
            pa.field("items", pa.list_(pa.int64()), nullable=True),
            pa.field("pair", pa.list_(pa.string(), 2), nullable=False),
            pa.field("amount", pa.decimal128(10, 2), nullable=True),
            pa.field("blob", pa.binary(), nullable=True),
            pa.field("game_date", pa.date32(), nullable=True),
        ]
    )
    values = [
        {
            "items": [],
            "pair": ["home", "away"],
            "amount": Decimal("1.20"),
            "blob": b"\x00\xff",
            "game_date": date(2026, 8, 27),
        },
        {
            "items": None,
            "pair": ["home", "away"],
            "amount": None,
            "blob": None,
            "game_date": None,
        },
        None,
    ]
    array = pa.array(values, type=nested_type)
    empty = canonical_arrow_array_scalar(array, 0)
    child_null = canonical_arrow_array_scalar(array, 1)
    parent_null = canonical_arrow_array_scalar(array, 2)

    assert empty.tag == "struct"
    assert decode_canonical_arrow_value(empty) == values[0]
    assert decode_canonical_arrow_value(child_null) == values[1]
    assert decode_canonical_arrow_value(parent_null) is None
    assert len({empty.value_sha256, child_null.value_sha256, parent_null.value_sha256}) == 3


def test_dictionary_categorical_and_enum_bind_inventory_and_ordering() -> None:
    categorical = pl.Series(["away", "home", None, "away"], dtype=pl.Categorical).to_arrow()
    enum = pl.Series(
        ["away", "home", None],
        dtype=pl.Enum(["home", "away", "neutral"]),
    ).to_arrow()
    categorical_receipt = canonical_arrow_array_scalar(categorical, 0)
    enum_receipt = canonical_arrow_array_scalar(enum, 0)

    assert categorical_receipt.logical_type.ordered is False
    assert enum_receipt.logical_type.ordered is True
    assert categorical_receipt.value_payload()["dictionary"] == [
        {"tag": "utf8", "value": "away"},
        {"tag": "utf8", "value": "home"},
    ]
    assert enum_receipt.value_payload()["dictionary"] == [
        {"tag": "utf8", "value": "home"},
        {"tag": "utf8", "value": "away"},
        {"tag": "utf8", "value": "neutral"},
    ]
    assert decode_canonical_arrow_value(categorical_receipt) == "away"
    assert decode_canonical_arrow_value(enum_receipt) == "away"
    assert not compare_canonical_arrow_values(categorical_receipt, enum_receipt)


def test_dictionary_scalar_retains_complete_dictionary_context() -> None:
    dictionary = pa.array(["red", "green", "blue"], type=pa.string())
    array = pa.DictionaryArray.from_arrays(
        pa.array([2], type=pa.uint8()),
        dictionary,
        ordered=True,
    )
    receipt = canonical_arrow_scalar(array[0], array.type)

    assert receipt.value_payload()["dictionary"] == [
        {"tag": "utf8", "value": "red"},
        {"tag": "utf8", "value": "green"},
        {"tag": "utf8", "value": "blue"},
    ]
    assert decode_canonical_arrow_value(receipt) == "blue"


def test_dictionary_null_index_and_valid_null_selection_do_not_alias() -> None:
    dictionary = pa.array([None, "home"], type=pa.string())
    null_index = pa.DictionaryArray.from_arrays(
        pa.array([None], type=pa.int8()),
        dictionary,
    )
    valid_null = pa.DictionaryArray.from_arrays(
        pa.array([0], type=pa.int8()),
        dictionary,
    )

    null_index_value = canonical_arrow_array_scalar(null_index, 0)
    valid_null_value = canonical_arrow_array_scalar(valid_null, 0)

    assert null_index_value.value_payload()["selection_valid"] is False
    assert valid_null_value.value_payload()["selection_valid"] is True
    assert not compare_canonical_arrow_values(null_index_value, valid_null_value)
    assert (
        CanonicalArrowValueV1.from_canonical_bytes(valid_null_value.to_canonical_bytes())
        == valid_null_value
    )

    missing_validity = valid_null_value.to_dict()
    cast("dict[str, Any]", missing_validity["value"]).pop("selection_valid")
    with pytest.raises(CanonicalArrowValueError, match="keys"):
        CanonicalArrowValueV1.from_canonical_bytes(_canonical_json(missing_validity))


def test_decoder_value_uses_exact_committed_dictionary_context() -> None:
    dtype = pa.dictionary(pa.uint8(), pa.string(), ordered=True)
    committed = pa.DictionaryArray.from_arrays(
        pa.array([2], type=pa.uint8()),
        pa.array(["red", "green", "blue"], type=pa.string()),
        ordered=True,
    )
    committed_value = canonical_arrow_array_scalar(committed, 0)
    singleton_value = canonical_arrow_scalar("blue", dtype)
    contextual_value = canonical_arrow_scalar(
        "blue",
        dtype,
        dictionary_context=committed,
    )

    assert not compare_canonical_arrow_values(committed_value, singleton_value)
    assert compare_canonical_arrow_values(committed_value, contextual_value)
    assert contextual_value.value_payload()["dictionary"] == [
        {"tag": "utf8", "value": "red"},
        {"tag": "utf8", "value": "green"},
        {"tag": "utf8", "value": "blue"},
    ]

    with pytest.raises(CanonicalArrowValueError, match="absent from the committed"):
        canonical_arrow_scalar("away", dtype, dictionary_context=committed)
    with pytest.raises(CanonicalArrowValueError, match="one materialized unified"):
        canonical_arrow_scalar(
            "blue",
            dtype,
            dictionary_context=pa.chunked_array([committed, committed]),
        )


def test_dictionary_descriptor_rejects_forged_child_identity_and_nullability() -> None:
    descriptor = canonical_arrow_type(
        pa.dictionary(pa.int8(), pa.string(), ordered=False)
    ).to_dict()

    for ordinal, key, value in (
        (0, "name", "forged_index"),
        (0, "nullable", True),
        (1, "name", "forged_value"),
        (1, "nullable", False),
    ):
        forged = cast("dict[str, Any]", copy.deepcopy(descriptor))
        forged["descriptor"]["children"][ordinal][key] = value
        with pytest.raises(CanonicalArrowValueError, match="identity or nullability"):
            ArrowLogicalTypeV1.from_canonical_bytes(_canonical_json(forged))


def test_chunked_and_nonzero_offset_arrays_use_exact_selected_value() -> None:
    base = pl.DataFrame(
        {
            "nested": pl.Series(
                [[99], [], None, [3, None, 5], [88]],
                dtype=pl.List(pl.Int64),
            ),
            "amount": pl.Series(
                [
                    Decimal("9.99"),
                    Decimal("1.20"),
                    None,
                    Decimal("-3.40"),
                    Decimal("8.88"),
                ],
                dtype=pl.Decimal(12, 2),
            ),
        }
    ).slice(1, 3)
    table = base.to_arrow()
    amount = table.column("amount")
    assert amount.chunk(0).offset == 1
    chunked = pa.chunked_array([pa.array([1, 2]), pa.array([3, 4])])

    assert decode_canonical_arrow_value(canonical_arrow_array_scalar(amount, 0)) == Decimal("1.20")
    assert decode_canonical_arrow_value(canonical_arrow_array_scalar(amount, 1)) is None
    assert decode_canonical_arrow_value(canonical_arrow_array_scalar(chunked, 2)) == 3


def test_null_value_retains_declared_logical_type() -> None:
    integer_null = canonical_arrow_scalar(None, pa.int64())
    string_null = canonical_arrow_scalar(None, pa.string())
    null_type = canonical_arrow_scalar(None, pa.null())

    assert integer_null.tag == string_null.tag == null_type.tag == "null"
    assert (
        len(
            {
                integer_null.logical_type_sha256,
                string_null.logical_type_sha256,
                null_type.logical_type_sha256,
            }
        )
        == 3
    )
    assert not compare_canonical_arrow_values(integer_null, string_null)


@pytest.mark.parametrize(
    ("value", "dtype", "match"),
    [
        (True, pa.int64(), "exact Python int"),
        (1, pa.bool_(), "exact Python bool"),
        (1, pa.float64(), "exact Python float"),
        ("1", pa.int64(), "exact Python int"),
        (bytearray(b"x"), pa.binary(), "immutable exact bytes"),
        (datetime(2026, 8, 27), pa.date32(), "exact Python date"),
        ("2026-08-27", pa.date32(), "exact Python date"),
        (datetime(2026, 8, 27, tzinfo=UTC), pa.timestamp("us"), "unzon"),
        (datetime(2026, 8, 27), pa.timestamp("us", tz="UTC"), "timezone"),
        (
            datetime(2026, 8, 27, tzinfo=UTC),
            pa.timestamp("us", tz="America/New_York"),
            "timezone",
        ),
        ((1, 2), pa.list_(pa.int64()), "exact Python list"),
        ([1], pa.list_(pa.int64(), 2), "wrong length"),
        ({"x": 1, "foreign": 2}, pa.struct([("x", pa.int64())]), "exact field"),
        (Decimal("NaN"), pa.decimal128(10, 2), "finite exact Decimal"),
        (Decimal("Infinity"), pa.decimal128(10, 2), "finite exact Decimal"),
    ],
)
def test_unsafe_or_implicit_python_coercions_fail_closed(
    value: object,
    dtype: pa.DataType,
    match: str,
) -> None:
    with pytest.raises(CanonicalArrowValueError, match=match):
        canonical_arrow_scalar(value, dtype)


def test_decimal_rounding_and_fixed_binary_length_fail_closed() -> None:
    with pytest.raises(CanonicalArrowValueError, match="cannot be represented"):
        canonical_arrow_scalar(Decimal("1.234"), pa.decimal128(10, 2))
    with pytest.raises(CanonicalArrowValueError, match="cannot be represented"):
        canonical_arrow_scalar(b"x", pa.binary(2))


@pytest.mark.parametrize(
    "dtype",
    [
        pa.map_(pa.string(), pa.int64()),
        pa.union([pa.field("a", pa.int64()), pa.field("b", pa.string())], "sparse"),
        pa.run_end_encoded(pa.int16(), pa.string()),
        pa.string_view(),
        pa.binary_view(),
    ],
)
def test_unsupported_arrow_families_fail_closed(dtype: pa.DataType) -> None:
    with pytest.raises(CanonicalArrowValueError, match="unsupported"):
        canonical_arrow_type(dtype)


def test_hostile_object_never_enters_identity_through_stringification() -> None:
    class Hostile:
        def __str__(self) -> str:
            return "trusted"

        def __repr__(self) -> str:
            return "trusted"

    with pytest.raises(CanonicalArrowValueError, match="exact Python"):
        canonical_arrow_scalar(Hostile(), pa.string())


def test_canonical_bytes_reject_whitespace_reordering_duplicates_and_nonfinite_json() -> None:
    receipt = canonical_arrow_scalar(1.5, pa.float64())
    encoded = receipt.to_canonical_bytes()
    payload = json.loads(encoded)

    with pytest.raises(CanonicalArrowValueError, match="not exact"):
        CanonicalArrowValueV1.from_canonical_bytes(b" " + encoded)

    reordered = json.dumps(
        {key: payload[key] for key in reversed(payload)},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    assert reordered != encoded
    with pytest.raises(CanonicalArrowValueError, match="not exact"):
        CanonicalArrowValueV1.from_canonical_bytes(reordered)

    duplicate = encoded.replace(
        b'"kind":"canonical_arrow_value",',
        b'"kind":"canonical_arrow_value","kind":"canonical_arrow_value",',
        1,
    )
    with pytest.raises(CanonicalArrowValueError, match="duplicate"):
        CanonicalArrowValueV1.from_canonical_bytes(duplicate)

    nonfinite = encoded.replace(b'"node_count":1', b'"node_count":NaN', 1)
    with pytest.raises(CanonicalArrowValueError, match="forbidden number"):
        CanonicalArrowValueV1.from_canonical_bytes(nonfinite)

    with pytest.raises(CanonicalArrowValueError, match="UTF-8"):
        CanonicalArrowValueV1.from_canonical_bytes(encoded[:-1] + b"\xff")


def test_canonical_json_rejects_hostile_integer_before_python_digit_conversion() -> None:
    receipt = canonical_arrow_scalar(7, pa.int64())
    hostile = receipt.to_canonical_bytes().replace(
        b'"node_count":1',
        b'"node_count":' + (b"9" * 5_000),
        1,
    )

    with pytest.raises(CanonicalArrowValueError, match="integer token exceeds"):
        CanonicalArrowValueV1.from_canonical_bytes(hostile)

    hostile_integer_text = receipt.to_dict()
    hostile_integer_text["value"] = {"tag": "integer", "value": "9" * 5_000}
    with pytest.raises(CanonicalArrowValueError, match="exceeds its logical type"):
        CanonicalArrowValueV1.from_canonical_bytes(_canonical_json(hostile_integer_text))


def test_canonical_bytes_reject_extra_missing_wrong_exact_types_and_resealed_value_shape() -> None:
    receipt = canonical_arrow_scalar(7, pa.int64())
    payload = receipt.to_dict()

    extra = copy.deepcopy(payload)
    extra["foreign"] = True
    with pytest.raises(CanonicalArrowValueError, match="keys"):
        CanonicalArrowValueV1.from_canonical_bytes(_canonical_json(extra))

    missing = copy.deepcopy(payload)
    missing.pop("tag")
    with pytest.raises(CanonicalArrowValueError, match="keys"):
        CanonicalArrowValueV1.from_canonical_bytes(_canonical_json(missing))

    boolean_count = copy.deepcopy(payload)
    boolean_count["node_count"] = True
    with pytest.raises(CanonicalArrowValueError, match="node_count"):
        CanonicalArrowValueV1.from_canonical_bytes(_canonical_json(boolean_count))

    wrong_tag = copy.deepcopy(payload)
    wrong_tag["value"] = {"tag": "utf8", "value": "7"}
    wrong_tag["tag"] = "utf8"
    with pytest.raises(CanonicalArrowValueError, match="tag differs"):
        CanonicalArrowValueV1.from_canonical_bytes(_canonical_json(wrong_tag))


def test_nested_reorder_duplicate_struct_field_and_dictionary_value_fail() -> None:
    struct_type = pa.struct([("a", pa.int64()), ("b", pa.int64())])
    receipt = canonical_arrow_scalar({"a": 1, "b": 2}, struct_type)
    payload = receipt.to_dict()
    fields = cast("dict[str, Any]", payload["value"])["fields"]
    assert isinstance(fields, list)
    fields[0], fields[1] = fields[1], fields[0]
    with pytest.raises(CanonicalArrowValueError, match="order or identity"):
        CanonicalArrowValueV1.from_canonical_bytes(_canonical_json(payload))

    dictionary = pa.DictionaryArray.from_arrays(
        pa.array([0], type=pa.int8()),
        pa.array(["same", "other"]),
    )
    dictionary_payload = canonical_arrow_array_scalar(dictionary, 0).to_dict()
    values = cast("dict[str, Any]", dictionary_payload["value"])["dictionary"]
    assert isinstance(values, list)
    values[1] = copy.deepcopy(values[0])
    with pytest.raises(CanonicalArrowValueError, match="duplicate"):
        CanonicalArrowValueV1.from_canonical_bytes(_canonical_json(dictionary_payload))


def test_malformed_float_binary_integer_temporal_and_decimal_payloads_fail() -> None:
    cases = [
        (
            canonical_arrow_scalar(1.5, pa.float32()),
            {"tag": "float", "bits": "7FC00000"},
            "lowercase",
        ),
        (
            canonical_arrow_scalar(b"\x00", pa.binary()),
            {"tag": "binary", "byte_length": 1, "hex": "0"},
            "lowercase hex",
        ),
        (canonical_arrow_scalar(1, pa.int8()), {"tag": "integer", "value": "01"}, "integer text"),
        (
            canonical_arrow_scalar(time(1), pa.time64("ns")),
            {"tag": "time", "ticks": str(86_400_000_000_000)},
            "outside one day",
        ),
        (
            canonical_arrow_scalar(Decimal("1.20"), pa.decimal128(3, 2)),
            {"tag": "decimal", "unscaled": "1000"},
            "logical type",
        ),
    ]
    for receipt, value, match in cases:
        payload = receipt.to_dict()
        payload["value"] = value
        payload["tag"] = value["tag"]
        with pytest.raises(CanonicalArrowValueError, match=match):
            CanonicalArrowValueV1.from_canonical_bytes(_canonical_json(payload))


def test_shape_and_byte_gates_reject_before_unbounded_decode() -> None:
    deeply_nested = b'{"a":' + b"[" * 65 + b"0" + b"]" * 65 + b"}"
    with pytest.raises(CanonicalArrowValueError, match="shape bound"):
        CanonicalArrowValueV1.from_canonical_bytes(deeply_nested)

    with pytest.raises(CanonicalArrowValueError, match="bounded exact bytes"):
        CanonicalArrowValueV1.from_canonical_bytes(b"x" * (8 * 1024 * 1024 + 1))


def test_value_budget_is_cumulative_atomic_and_checked_before_commit() -> None:
    limits = ValueBudgetLimits(
        max_nodes=2,
        max_depth=4,
        max_utf8_bytes=3,
        max_binary_bytes=2,
        max_container_items=2,
        max_canonical_bytes=10_000,
    )
    budget = ValueBudget(limits=limits)
    canonical_arrow_scalar("ab", pa.string(), budget=budget)
    before = copy.copy(budget)

    with pytest.raises(CanonicalArrowValueError, match="UTF-8 bytes"):
        canonical_arrow_scalar("cd", pa.string(), budget=budget)
    assert budget == before

    binary_budget = ValueBudget(limits=limits)
    canonical_arrow_scalar(b"\x00", pa.binary(), budget=binary_budget)
    with pytest.raises(CanonicalArrowValueError, match="binary bytes"):
        canonical_arrow_scalar(b"\x01\x02", pa.binary(), budget=binary_budget)


def test_value_budget_parser_reserves_exact_counts_and_bytes() -> None:
    receipt = canonical_arrow_scalar([1, None], pa.list_(pa.int64()))
    budget = ValueBudget()
    parsed = CanonicalArrowValueV1.from_canonical_bytes(
        receipt.to_canonical_bytes(),
        budget=budget,
    )

    assert parsed == receipt
    assert budget.nodes == receipt.node_count
    assert budget.max_depth_observed == receipt.max_depth
    assert budget.container_items == receipt.container_items
    assert budget.canonical_bytes == len(receipt.to_canonical_bytes())


def test_caller_budget_rejects_before_payload_or_arrow_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limits = ValueBudgetLimits(
        max_nodes=1,
        max_depth=4,
        max_utf8_bytes=32,
        max_binary_bytes=32,
        max_container_items=1,
        max_canonical_bytes=4_096,
    )
    exhausted = ValueBudget(limits=limits, nodes=1)
    before = copy.copy(exhausted)
    payload_calls = 0
    type_calls = 0
    original_payload = codec._payload_from_array
    original_type = codec.canonical_arrow_type

    def payload_spy(*args: Any, **kwargs: Any) -> dict[str, object]:
        nonlocal payload_calls
        payload_calls += 1
        return original_payload(*args, **kwargs)

    def type_spy(dtype: pa.DataType) -> object:
        nonlocal type_calls
        type_calls += 1
        return original_type(dtype)

    monkeypatch.setattr(codec, "_payload_from_array", payload_spy)
    monkeypatch.setattr(codec, "canonical_arrow_type", type_spy)
    with pytest.raises(CanonicalArrowValueError, match="value nodes"):
        canonical_arrow_scalar(7, pa.int64(), budget=exhausted)
    assert exhausted == before
    assert payload_calls == 0
    assert type_calls == 0

    arrow_calls = 0
    json_calls = 0
    original_dumps = codec.json.dumps

    def arrow_spy(*args: object, **kwargs: object) -> pa.Array:
        nonlocal arrow_calls
        arrow_calls += 1
        raise AssertionError("Arrow construction must not run")

    def json_spy(*args: Any, **kwargs: Any) -> str:
        nonlocal json_calls
        json_calls += 1
        return original_dumps(*args, **kwargs)

    monkeypatch.setattr(codec, "_array_from_scalar", arrow_spy)
    monkeypatch.setattr(codec.json, "dumps", json_spy)
    impossible_budget = ValueBudget(
        limits=ValueBudgetLimits(
            max_nodes=4,
            max_depth=4,
            max_utf8_bytes=32,
            max_binary_bytes=32,
            max_container_items=4,
            max_canonical_bytes=1,
        )
    )
    with pytest.raises(CanonicalArrowValueError, match="canonical bytes"):
        canonical_arrow_scalar(7, pa.int64(), budget=impossible_budget)
    assert arrow_calls == 0
    assert type_calls == 0
    assert json_calls == 0

    container_budget = ValueBudget(limits=limits)
    with pytest.raises(CanonicalArrowValueError, match="container items"):
        canonical_arrow_scalar([1, 2], pa.list_(pa.int64()), budget=container_budget)
    assert arrow_calls == 0
    assert json_calls == 0


def test_canonical_serialization_pre_sizes_before_json_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    json_calls = 0
    original_dumps = codec.json.dumps

    def json_spy(*args: Any, **kwargs: Any) -> str:
        nonlocal json_calls
        json_calls += 1
        return original_dumps(*args, **kwargs)

    monkeypatch.setattr(codec.json, "dumps", json_spy)
    budget = ValueBudget(
        limits=ValueBudgetLimits(
            max_nodes=4,
            max_depth=4,
            max_utf8_bytes=2_000,
            max_binary_bytes=32,
            max_container_items=4,
            max_canonical_bytes=500,
        )
    )

    with pytest.raises(CanonicalArrowValueError, match="byte bound"):
        canonical_arrow_scalar("x" * 1_000, pa.string(), budget=budget)
    assert json_calls == 0

    type_specific_impossible = ValueBudget(
        limits=ValueBudgetLimits(
            max_canonical_bytes=codec.MIN_CANONICAL_ARROW_VALUE_BYTES,
        )
    )
    with pytest.raises(CanonicalArrowValueError, match="byte bound"):
        canonical_arrow_scalar(False, pa.bool_(), budget=type_specific_impossible)
    assert json_calls == 0


def test_minimum_receipt_budget_is_an_exact_admitted_boundary() -> None:
    budget = ValueBudget(
        limits=ValueBudgetLimits(
            max_canonical_bytes=codec.MIN_CANONICAL_ARROW_VALUE_BYTES,
        )
    )

    receipt = canonical_arrow_scalar(None, pa.null(), budget=budget)

    assert len(receipt.to_canonical_bytes()) == codec.MIN_CANONICAL_ARROW_VALUE_BYTES
    assert budget.canonical_bytes == codec.MIN_CANONICAL_ARROW_VALUE_BYTES


def test_parser_budget_rejects_before_json_decode_or_payload_walk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoded = canonical_arrow_scalar(7, pa.int64()).to_canonical_bytes()
    limits = ValueBudgetLimits(
        max_nodes=1,
        max_depth=4,
        max_utf8_bytes=32,
        max_binary_bytes=32,
        max_container_items=4,
        max_canonical_bytes=len(encoded),
    )
    bytes_exhausted = ValueBudget(limits=limits, canonical_bytes=len(encoded))
    json_calls = 0
    original_loads = codec.json.loads

    def json_spy(*args: Any, **kwargs: Any) -> object:
        nonlocal json_calls
        json_calls += 1
        return original_loads(*args, **kwargs)

    monkeypatch.setattr(codec.json, "loads", json_spy)
    with pytest.raises(CanonicalArrowValueError, match="canonical bytes"):
        CanonicalArrowValueV1.from_canonical_bytes(encoded, budget=bytes_exhausted)
    assert json_calls == 0


@pytest.mark.parametrize(
    ("dtype", "ticks"),
    [
        (pa.timestamp("s"), 2**63 - 1),
        (pa.date32(), 2**31 - 1),
        (pa.date64(), 1),
        (pa.date64(), 2**63 - 1),
        (pa.time64("ns"), 1),
        (pa.duration("s"), 2**63 - 1),
    ],
)
def test_extreme_temporal_ticks_return_exact_arrow_scalar_fallback(
    dtype: pa.DataType,
    ticks: int,
) -> None:
    raw = ticks.to_bytes(dtype.bit_width // 8, byteorder="little", signed=True)
    array = pa.Array.from_buffers(dtype, 1, [None, pa.py_buffer(raw)])
    receipt = canonical_arrow_array_scalar(array, 0)

    assert CanonicalArrowValueV1.from_canonical_bytes(receipt.to_canonical_bytes()) == receipt
    decoded = decode_canonical_arrow_value(receipt)
    assert isinstance(decoded, pa.Scalar)
    assert decoded.value == ticks


def test_duplicate_struct_field_names_fail_closed_before_value_decode() -> None:
    duplicate_names = pa.struct(
        [
            pa.field("score", pa.int64()),
            pa.field("score", pa.string()),
        ]
    )

    with pytest.raises(CanonicalArrowValueError, match="must be unique"):
        canonical_arrow_type(duplicate_names)


def test_checked_arithmetic_rejects_bool_negative_and_overflow() -> None:
    assert checked_add(2, 3, maximum=5, label="cells") == 5
    assert checked_product(2, 3, maximum=6, label="cells") == 6
    for callback in (
        lambda: checked_add(True, 1, maximum=10),
        lambda: checked_add(-1, 1, maximum=10),
        lambda: checked_add(6, 5, maximum=10),
        lambda: checked_product(True, 1, maximum=10),
        lambda: checked_product(-1, 1, maximum=10),
        lambda: checked_product(6, 2, maximum=10),
    ):
        with pytest.raises(CanonicalArrowValueError):
            callback()


def test_exact_type_participates_in_comparison() -> None:
    int32 = canonical_arrow_scalar(1, pa.int32())
    int64 = canonical_arrow_scalar(1, pa.int64())
    int32_copy = CanonicalArrowValueV1.from_canonical_bytes(int32.to_canonical_bytes())

    assert compare_canonical_arrow_values(int32, int32_copy)
    assert compare_canonical_arrow_values(int32.to_canonical_bytes(), int32_copy)
    assert not compare_canonical_arrow_values(int32, int64)
