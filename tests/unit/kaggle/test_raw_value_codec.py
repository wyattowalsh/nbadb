from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import sqlite3
from typing import cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from nbadb.kaggle.raw_value_codec import (
    RAW_VALUE_CODEC_SCHEMA_VERSION,
    RAW_VALUE_CODEC_TAG,
    RawScalarValue,
    RawValueCodecError,
    decode_raw_value,
    encode_raw_value,
)

_ENVELOPE_KEYS = {
    "byte_length",
    "kind",
    "payload_base64",
    "schema_version",
    "tag",
    "value_sha256",
}


class _TextSubclass(str):
    pass


class _BytesSubclass(bytes):
    pass


def _envelope(value: RawScalarValue) -> dict[str, object]:
    parsed = json.loads(encode_raw_value(value))
    assert type(parsed) is dict
    return cast("dict[str, object]", parsed)


def _dump(envelope: dict[str, object]) -> str:
    return json.dumps(envelope, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _digest(kind: str, payload: bytes) -> str:
    domain = f"{RAW_VALUE_CODEC_TAG}\x00v{RAW_VALUE_CODEC_SCHEMA_VERSION}\x00".encode("ascii")
    return hashlib.sha256(domain + kind.encode("ascii") + b"\x00" + payload).hexdigest()


@pytest.mark.parametrize(
    ("value", "kind", "payload"),
    [
        (None, "null", None),
        (b"", "bytes", ""),
        ("", "text", ""),
        (b"\x00\xff", "bytes", "AP8="),
        ("é", "text", "w6k="),
    ],
)
def test_version_one_golden_envelopes_are_exact_and_deterministic(
    value: RawScalarValue,
    kind: str,
    payload: str | None,
) -> None:
    encoded = encode_raw_value(value)
    envelope = _envelope(value)

    assert encoded == encode_raw_value(value)
    assert encoded.isascii()
    assert set(envelope) == _ENVELOPE_KEYS
    assert envelope == {
        "byte_length": None
        if value is None
        else len(cast("bytes | str", value).encode("utf-8"))
        if type(value) is str
        else len(cast("bytes", value)),
        "kind": kind,
        "payload_base64": payload,
        "schema_version": 1,
        "tag": "nbadb.raw.scalar",
        "value_sha256": _digest(
            kind,
            b""
            if value is None
            else value.encode("utf-8")
            if type(value) is str
            else cast("bytes", value),
        ),
    }
    assert decode_raw_value(encoded) == value
    assert type(decode_raw_value(encoded)) is type(value)


def test_null_empty_bytes_and_empty_text_have_distinct_encodings() -> None:
    encoded = {encode_raw_value(value) for value in (None, b"", "")}

    assert len(encoded) == 3
    assert decode_raw_value(encode_raw_value(None)) is None
    assert decode_raw_value(encode_raw_value(b"")) == b""
    assert decode_raw_value(encode_raw_value("")) == ""


@settings(max_examples=250, deadline=None)
@given(
    st.one_of(
        st.none(),
        st.binary(max_size=4096),
        st.text(max_size=2048),
    )
)
def test_arbitrary_null_binary_and_text_values_round_trip(value: RawScalarValue) -> None:
    encoded = encode_raw_value(value)
    decoded = decode_raw_value(encoded)

    assert decoded == value
    assert type(decoded) is type(value)
    assert encode_raw_value(decoded) == encoded


def test_csv_and_sqlite_text_projections_preserve_exact_scalar_kinds() -> None:
    values: list[RawScalarValue] = [None, b"", "", b"\x00\xff\n", 'comma,quote"\nΩ']
    encoded = [encode_raw_value(value) for value in values]

    csv_buffer = io.StringIO(newline="")
    csv.writer(csv_buffer).writerow(encoded)
    csv_buffer.seek(0)
    csv_values = next(csv.reader(csv_buffer))

    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(
            "CREATE TABLE raw_values (ordinal INTEGER PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO raw_values (ordinal, value) VALUES (?, ?)",
            enumerate(encoded),
        )
        sqlite_values = [
            str(row[0])
            for row in connection.execute("SELECT value FROM raw_values ORDER BY ordinal")
        ]
    finally:
        connection.close()

    assert [decode_raw_value(value) for value in csv_values] == values
    assert [type(decode_raw_value(value)) for value in csv_values] == [type(v) for v in values]
    assert [decode_raw_value(value) for value in sqlite_values] == values
    assert [type(decode_raw_value(value)) for value in sqlite_values] == [type(v) for v in values]


@pytest.mark.parametrize(
    "value",
    [
        0,
        1.0,
        False,
        bytearray(b"value"),
        memoryview(b"value"),
        _TextSubclass("value"),
        _BytesSubclass(b"value"),
        [],
        {},
    ],
)
def test_encoder_rejects_coercible_or_foreign_scalar_types(value: object) -> None:
    with pytest.raises(RawValueCodecError, match="exactly null, bytes, or text"):
        encode_raw_value(cast("RawScalarValue", value))


def test_encoder_rejects_non_utf8_python_text() -> None:
    with pytest.raises(RawValueCodecError, match="not valid UTF-8"):
        encode_raw_value("\ud800")


@pytest.mark.parametrize(
    "value",
    [
        None,
        b"encoded",
        1,
        True,
        bytearray(b"encoded"),
        _TextSubclass(encode_raw_value(b"encoded")),
    ],
)
def test_decoder_requires_exact_text_input(value: object) -> None:
    with pytest.raises(RawValueCodecError, match="must be exactly text"):
        decode_raw_value(cast("str", value))


@pytest.mark.parametrize(
    "encoded",
    ["", "null", "[]", "{", encode_raw_value(b"value")[:-1]],
)
def test_malformed_or_truncated_json_is_rejected(encoded: str) -> None:
    with pytest.raises(RawValueCodecError):
        decode_raw_value(encoded)


def test_duplicate_extra_missing_and_noncanonical_json_are_rejected() -> None:
    encoded = encode_raw_value(b"value")
    envelope = _envelope(b"value")
    extra = {**envelope, "foreign": "field"}
    missing = dict(envelope)
    del missing["tag"]
    duplicate = encoded[:-1] + f',"tag":"{RAW_VALUE_CODEC_TAG}"}}'
    pretty = json.dumps(envelope, indent=2, sort_keys=True)

    for mutated in (_dump(extra), _dump(missing), duplicate, pretty, f"{encoded}\n"):
        with pytest.raises(RawValueCodecError):
            decode_raw_value(mutated)


def test_nonfinite_json_number_is_rejected_before_schema_validation() -> None:
    encoded = encode_raw_value(b"value").replace('"schema_version":1', '"schema_version":NaN')

    with pytest.raises(RawValueCodecError, match="non-finite"):
        decode_raw_value(encoded)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("schema_version", True),
        ("schema_version", "1"),
        ("tag", "nbadb.raw.scalar.v1"),
        ("tag", 1),
        ("kind", "binary"),
        ("kind", 1),
    ],
)
def test_schema_version_tag_and_kind_are_strict(field: str, value: object) -> None:
    envelope = _envelope(b"value")
    envelope[field] = value

    with pytest.raises(RawValueCodecError):
        decode_raw_value(_dump(envelope))


@pytest.mark.parametrize("payload", ["YWJ", "YWJj=", "YWJj\n", "YWJ*", "_WJj"])
def test_truncated_malformed_or_noncanonical_base64_is_rejected(payload: str) -> None:
    envelope = _envelope(b"abc")
    envelope["payload_base64"] = payload

    with pytest.raises(RawValueCodecError, match="base64|digest"):
        decode_raw_value(_dump(envelope))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("byte_length", 4),
        ("byte_length", -1),
        ("byte_length", True),
        ("byte_length", "3"),
        ("payload_base64", None),
        ("payload_base64", ["YWJj"]),
        ("value_sha256", "0" * 64),
        ("value_sha256", "A" * 64),
        ("value_sha256", True),
    ],
)
def test_payload_metadata_and_digest_mutations_are_rejected(field: str, value: object) -> None:
    envelope = _envelope(b"abc")
    envelope[field] = value

    with pytest.raises(RawValueCodecError):
        decode_raw_value(_dump(envelope))


@pytest.mark.parametrize(
    ("field", "value"),
    [("payload_base64", ""), ("byte_length", 0)],
)
def test_null_envelope_cannot_carry_empty_payload_metadata(field: str, value: object) -> None:
    envelope = _envelope(None)
    envelope[field] = value

    with pytest.raises(RawValueCodecError, match="must not contain a payload"):
        decode_raw_value(_dump(envelope))


def test_null_semantic_digest_is_revalidated() -> None:
    envelope = _envelope(None)
    envelope["value_sha256"] = "0" * 64

    with pytest.raises(RawValueCodecError, match="semantic digest"):
        decode_raw_value(_dump(envelope))


def test_text_kind_rejects_non_utf8_bytes_even_with_matching_digest() -> None:
    payload = b"\xff"
    envelope = _envelope(payload)
    envelope["kind"] = "text"
    envelope["value_sha256"] = _digest("text", payload)

    with pytest.raises(RawValueCodecError, match="text payload is not valid UTF-8"):
        decode_raw_value(_dump(envelope))


def test_kind_mutation_is_bound_by_the_semantic_digest() -> None:
    envelope = _envelope(b"valid UTF-8")
    envelope["kind"] = "text"

    with pytest.raises(RawValueCodecError, match="semantic digest"):
        decode_raw_value(_dump(envelope))


def test_payload_base64_mutation_is_bound_by_length_and_digest() -> None:
    envelope = _envelope(b"abc")
    replacement = b"abd"
    envelope["payload_base64"] = base64.b64encode(replacement).decode("ascii")

    with pytest.raises(RawValueCodecError, match="semantic digest"):
        decode_raw_value(_dump(envelope))
