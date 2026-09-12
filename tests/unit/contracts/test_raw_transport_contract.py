from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from nbadb.contracts import raw_transport_contract
from nbadb.contracts.raw_transport_contract import (
    RAW_TRANSPORT_ADAPTER,
    LiveHttpTransportV1,
    StaticSnapshotTransportV1,
    StatsHttpTransportV1,
    canonical_transport_payload,
    source_family_for_transport,
    validate_raw_transport,
)


def test_public_exports_are_exact() -> None:
    assert raw_transport_contract.__all__ == [
        "RAW_TRANSPORT_ADAPTER",
        "HTTPStatus",
        "LiveHttpTransportV1",
        "RawTransportV1",
        "SourceFamily",
        "StaticSnapshotTransportV1",
        "StatsHttpTransportV1",
        "canonical_transport_payload",
        "source_family_for_transport",
        "validate_raw_transport",
    ]


@pytest.mark.parametrize(
    ("payload", "expected_type", "expected_family"),
    [
        (
            {
                "transport_kind": "stats_http",
                "status_code": 200,
                "effective_status_code": 200,
            },
            StatsHttpTransportV1,
            "stats",
        ),
        (
            {
                "transport_kind": "live_http",
                "status_code": 503,
                "effective_status_code": 502,
            },
            LiveHttpTransportV1,
            "live",
        ),
        (
            {
                "transport_kind": "live_http",
                "status_code": None,
                "effective_status_code": None,
            },
            LiveHttpTransportV1,
            "live",
        ),
        (
            {"transport_kind": "static_snapshot"},
            StaticSnapshotTransportV1,
            "static",
        ),
    ],
)
def test_transport_union_selects_one_exact_variant_without_coercion(
    payload: dict[str, object],
    expected_type: type[object],
    expected_family: str,
) -> None:
    transport = validate_raw_transport(payload)

    assert type(transport) is expected_type
    assert source_family_for_transport(transport) == expected_family


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"transport_kind": "http_response"},
        {"transport_kind": "static_provider_snapshot"},
        {"transport_kind": "unknown"},
        {"transport_kind": ["stats_http", "live_http"]},
        {"transport_kind": "stats_http", "source_family": "stats"},
        {"transport_kind": "live_http", "unexpected": None},
    ],
)
def test_transport_union_rejects_missing_unknown_legacy_ambiguous_and_extra_fields(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        validate_raw_transport(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"transport_kind": "static_snapshot", "status_code": 200},
        {"transport_kind": "static_snapshot", "status_code": None},
        {"transport_kind": "static_snapshot", "effective_status_code": 200},
        {
            "transport_kind": "static_snapshot",
            "status_code": 200,
            "effective_status_code": 200,
        },
    ],
)
def test_static_snapshot_never_accepts_fabricated_http_semantics(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        validate_raw_transport(payload)


@pytest.mark.parametrize(
    "status",
    [True, False, "200", 200.0, 99, 600],
)
@pytest.mark.parametrize("transport_kind", ["stats_http", "live_http"])
def test_http_status_is_strict_and_bounded(
    transport_kind: str,
    status: object,
) -> None:
    with pytest.raises(ValidationError):
        validate_raw_transport(
            {
                "transport_kind": transport_kind,
                "status_code": status,
                "effective_status_code": None,
            }
        )


@pytest.mark.parametrize("transport_kind", ["stats_http", "live_http"])
def test_effective_http_status_requires_an_observed_status(transport_kind: str) -> None:
    with pytest.raises(ValidationError, match="effective_status_code requires status_code"):
        validate_raw_transport(
            {
                "transport_kind": transport_kind,
                "status_code": None,
                "effective_status_code": 200,
            }
        )


def test_cross_variant_mutation_cannot_smuggle_http_fields_into_static() -> None:
    payload = canonical_transport_payload(
        {
            "transport_kind": "stats_http",
            "status_code": 204,
            "effective_status_code": 204,
        }
    )
    payload["transport_kind"] = "static_snapshot"

    with pytest.raises(ValidationError, match="extra_forbidden"):
        validate_raw_transport(payload)


@pytest.mark.parametrize(
    "model_type",
    [StatsHttpTransportV1, LiveHttpTransportV1],
)
def test_model_constructed_http_instances_are_revalidated(
    model_type: type[StatsHttpTransportV1] | type[LiveHttpTransportV1],
) -> None:
    transport = model_type.model_construct(
        transport_kind="stats_http" if model_type is StatsHttpTransportV1 else "live_http",
        status_code="200",
        effective_status_code=200,
    )

    with pytest.raises(ValidationError, match="int_type"):
        validate_raw_transport(transport)


def test_model_constructed_subclass_instance_is_revalidated() -> None:
    class StatsHttpTransportSubclass(StatsHttpTransportV1):
        pass

    transport = StatsHttpTransportSubclass.model_construct(
        transport_kind="stats_http",
        status_code=200,
        effective_status_code="200",
    )

    with pytest.raises(ValidationError, match="int_type"):
        validate_raw_transport(transport)


def test_preconstructed_static_instance_cannot_smuggle_http_status() -> None:
    transport = StaticSnapshotTransportV1.model_construct(transport_kind="static_snapshot")
    object.__setattr__(transport, "status_code", 200)

    with pytest.raises(ValidationError, match="extra_forbidden"):
        validate_raw_transport(transport)


def test_models_are_frozen() -> None:
    transport = validate_raw_transport(
        {
            "transport_kind": "stats_http",
            "status_code": 200,
            "effective_status_code": 200,
        }
    )

    with pytest.raises(ValidationError, match="frozen_instance"):
        transport.status_code = 201


@pytest.mark.parametrize(
    ("input_payload", "expected_payload"),
    [
        (
            {
                "effective_status_code": 200,
                "transport_kind": "stats_http",
                "status_code": 200,
            },
            {
                "transport_kind": "stats_http",
                "status_code": 200,
                "effective_status_code": 200,
            },
        ),
        (
            {"transport_kind": "live_http"},
            {
                "transport_kind": "live_http",
                "status_code": None,
                "effective_status_code": None,
            },
        ),
        (
            {"transport_kind": "static_snapshot"},
            {"transport_kind": "static_snapshot"},
        ),
    ],
)
def test_canonical_payload_has_exact_variant_keys_and_is_idempotent(
    input_payload: dict[str, object],
    expected_payload: dict[str, object],
) -> None:
    canonical = canonical_transport_payload(input_payload)

    assert canonical == expected_payload
    assert canonical_transport_payload(canonical) == canonical

    encoded = json.dumps(
        canonical,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    round_trip_encoded = json.dumps(
        canonical_transport_payload(json.loads(encoded)),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    assert hashlib.sha256(round_trip_encoded).digest() == hashlib.sha256(encoded).digest()


def test_json_schema_exposes_an_explicit_three_way_discriminator() -> None:
    schema = RAW_TRANSPORT_ADAPTER.json_schema()

    assert schema["discriminator"] == {
        "mapping": {
            "live_http": "#/$defs/LiveHttpTransportV1",
            "static_snapshot": "#/$defs/StaticSnapshotTransportV1",
            "stats_http": "#/$defs/StatsHttpTransportV1",
        },
        "propertyName": "transport_kind",
    }
    assert len(schema["oneOf"]) == 3
