from __future__ import annotations

import ast
import hashlib
import inspect
import json
from copy import copy
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from nbadb.contracts import independent_result_cell_builder as builder_module
from nbadb.contracts.declared_bodyless_packet import build_declared_bodyless_packet
from nbadb.contracts.independent_result_cell_builder import (
    IndependentResultCellBuilderError,
    build_independent_result_cell_authority,
)
from nbadb.contracts.raw_result_cell_authority import validate_raw_result_cell_authority
from nbadb.extract.nba_api_adapter import fetch_static_packet
from tests.unit.contracts.test_raw_result_cell_authority import (
    _combined_case,
    _static_case,
    _stats_case,
    _wide_plus_lossless_case,
)

if TYPE_CHECKING:
    from nbadb.contracts.raw_request_authority import RawRequestAuthorityBundleV2

_SHA = "f" * 64


def _static_packet_source(
    bundle: RawRequestAuthorityBundleV2,
) -> tuple[object, bytes]:
    observation = next(
        item for item in bundle.observations if item.attempt.source_family == "static"
    )
    source = fetch_static_packet(observation.attempt.endpoint_id)
    packet_bytes = json.dumps(
        source.frame.rows(),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    packet = build_declared_bodyless_packet(
        observation=observation,
        expected_observation_sha256=observation.attempt.observation_sha256,
        expected_observation_record_sha256=observation.observation_record_sha256,
        packet_bytes=packet_bytes,
    )
    return packet, packet_bytes


def _build(
    bundle: RawRequestAuthorityBundleV2,
    *,
    packets: tuple[object, ...] = (),
    packet_bytes: tuple[object, ...] = (),
    raw_pin: object | None = None,
    packet_pins: object | None = None,
    known_secrets: tuple[str | bytes, ...] = (),
):
    exact_packet_pins = (
        tuple(item.packet_authority_sha256 for item in packets)
        if packet_pins is None
        else packet_pins
    )
    return build_independent_result_cell_authority(
        bundle,
        expected_raw_authority_bundle_sha256=(bundle.bundle_sha256 if raw_pin is None else raw_pin),
        declared_bodyless_packets=packets,
        expected_declared_bodyless_packet_authority_sha256s=exact_packet_pins,
        declared_bodyless_packet_bytes=packet_bytes,
        known_secrets=known_secrets,
    )


def test_rebuilds_stats_result_cells_from_exact_parser_input_bytes() -> None:
    bundle, cells = _stats_case()

    assert _build(bundle) == validate_raw_result_cell_authority(bundle, cells)


def test_rebuilds_static_result_cells_from_exact_declared_packet_bytes() -> None:
    bundle, cells = _static_case()
    packet, packet_bytes = _static_packet_source(bundle)

    assert _build(
        bundle,
        packets=(packet,),
        packet_bytes=(packet_bytes,),
    ) == validate_raw_result_cell_authority(bundle, cells)


def test_rebuilds_mixed_stats_and_static_authority_in_raw_semantic_order() -> None:
    bundle, cells = _combined_case()
    packet, packet_bytes = _static_packet_source(bundle)

    assert _build(
        bundle,
        packets=(packet,),
        packet_bytes=(packet_bytes,),
    ) == validate_raw_result_cell_authority(bundle, cells)


def test_ignores_non_wide_stats_occurrences_before_independent_decode_join() -> None:
    bundle, _lossless_cells = _wide_plus_lossless_case()

    assert _build(bundle) == validate_raw_result_cell_authority(bundle, ())


@pytest.mark.parametrize(
    ("raw_pin", "packet_pins", "packet_bytes"),
    [
        (_SHA, None, None),
        (None, (_SHA,), None),
        (None, None, (b"[]",)),
    ],
)
def test_rejects_mismatched_external_pins_and_packet_bytes(
    raw_pin: object | None,
    packet_pins: object | None,
    packet_bytes: tuple[object, ...] | None,
) -> None:
    bundle, _cells = _static_case()
    packet, exact_bytes = _static_packet_source(bundle)

    with pytest.raises(IndependentResultCellBuilderError):
        _build(
            bundle,
            packets=(packet,),
            packet_bytes=(exact_bytes,) if packet_bytes is None else packet_bytes,
            raw_pin=raw_pin,
            packet_pins=packet_pins,
        )


def test_rejects_orphan_and_duplicate_declared_bodyless_packets() -> None:
    static_bundle, _cells = _static_case()
    stats_bundle, _stats_cells = _stats_case()
    packet, packet_bytes = _static_packet_source(static_bundle)

    with pytest.raises(IndependentResultCellBuilderError):
        _build(stats_bundle, packets=(packet,), packet_bytes=(packet_bytes,))
    with pytest.raises(IndependentResultCellBuilderError):
        _build(
            static_bundle,
            packets=(packet, packet),
            packet_bytes=(packet_bytes, packet_bytes),
        )


@pytest.mark.parametrize("foreign", [[], [object()], (bytearray(b"[]"),)])
def test_requires_exact_packet_and_byte_tuples(foreign: object) -> None:
    bundle, _cells = _static_case()
    packet, packet_bytes = _static_packet_source(bundle)
    packets: object = (packet,)
    bytes_values: object = (packet_bytes,)
    pins: object = (packet.packet_authority_sha256,)
    if type(foreign) is list:
        packets = foreign
    else:
        bytes_values = foreign

    with pytest.raises(IndependentResultCellBuilderError):
        build_independent_result_cell_authority(
            bundle,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            declared_bodyless_packets=packets,
            expected_declared_bodyless_packet_authority_sha256s=pins,
            declared_bodyless_packet_bytes=bytes_values,
        )


def test_rejects_known_secret_material_in_stats_and_static_sources() -> None:
    stats_bundle, _stats_cells = _stats_case()
    static_bundle, _static_cells = _static_case()
    packet, packet_bytes = _static_packet_source(static_bundle)

    with pytest.raises(IndependentResultCellBuilderError) as stats_error:
        _build(stats_bundle, known_secrets=(b"resultSets",))
    with pytest.raises(IndependentResultCellBuilderError) as static_error:
        _build(
            static_bundle,
            packets=(packet,),
            packet_bytes=(packet_bytes,),
            known_secrets=(b"Alaa Abdelnaby",),
        )
    assert "resultSets" not in str(stats_error.value)
    assert "Alaa Abdelnaby" not in str(static_error.value)


def test_hostile_child_error_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    bundle, _cells = _stats_case()
    sentinel = "must-not-escape-result-cell-builder"

    def hostile(*_args: object, **_kwargs: object) -> object:
        raise IndependentResultCellBuilderError(sentinel)

    monkeypatch.setattr(builder_module, "decode_stats_projection_response", hostile)
    with pytest.raises(IndependentResultCellBuilderError) as error:
        _build(bundle)
    assert sentinel not in str(error.value)
    assert str(error.value) == (
        "result-cell source authorities failed exact independent reconstruction"
    )


def test_rejects_poisoned_stats_decoder_source_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _cells = _stats_case()
    observation = bundle.observations[0]
    parser_input = builder_module.decode_parser_input_object(bundle.objects[0])
    decoded = builder_module.decode_stats_projection_response(
        parser_input,
        endpoint_id=observation.attempt.endpoint_id,
        endpoint_contract_sha256=observation.attempt.endpoint_contract_sha256,
        provider_authority_sha256=observation.attempt.provider_authority_sha256,
    )
    poisoned = copy(decoded)
    object.__setattr__(poisoned, "parser_input_sha256", _SHA)

    monkeypatch.setattr(
        builder_module,
        "decode_stats_projection_response",
        lambda *_args, **_kwargs: poisoned,
    )
    with pytest.raises(IndependentResultCellBuilderError):
        _build(bundle)


def test_rejects_semantically_equal_stats_bytes_from_a_foreign_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _cells = _stats_case()
    exact_decode = builder_module.decode_parser_input_object

    monkeypatch.setattr(
        builder_module,
        "decode_parser_input_object",
        lambda value: exact_decode(value) + b" ",
    )
    with pytest.raises(IndependentResultCellBuilderError):
        _build(bundle)


def test_external_pin_preflight_precedes_child_traversal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _cells = _stats_case()
    traversed = False

    def hostile(*_args: object, **_kwargs: object) -> object:
        nonlocal traversed
        traversed = True
        raise AssertionError("must not traverse")

    monkeypatch.setattr(builder_module, "validate_raw_request_authority_bundle", hostile)
    with pytest.raises(IndependentResultCellBuilderError):
        _build(bundle, raw_pin=_SHA)
    assert traversed is False


def test_rejects_validator_substitution_after_external_pin_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _cells = _stats_case()
    substitute, _substitute_cells = _static_case()

    monkeypatch.setattr(
        builder_module,
        "validate_raw_request_authority_bundle",
        lambda _value: substitute,
    )
    with pytest.raises(IndependentResultCellBuilderError):
        _build(bundle)


def test_rejects_final_receipt_validator_substitution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _cells = _stats_case()
    substitute, substitute_cells = _static_case()
    substitute_receipt = validate_raw_result_cell_authority(substitute, substitute_cells)

    monkeypatch.setattr(
        builder_module,
        "validate_raw_result_cell_authority",
        lambda _bundle, _cells: substitute_receipt,
    )
    with pytest.raises(IndependentResultCellBuilderError):
        _build(bundle)


def test_rejects_resealed_root_on_foreign_final_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _cells = _stats_case()
    substitute, substitute_cells = _static_case()
    poisoned_receipt = copy(validate_raw_result_cell_authority(substitute, substitute_cells))
    object.__setattr__(
        poisoned_receipt,
        "raw_authority_bundle_sha256",
        bundle.bundle_sha256,
    )

    monkeypatch.setattr(
        builder_module,
        "validate_raw_result_cell_authority",
        lambda _bundle, _cells: poisoned_receipt,
    )
    with pytest.raises(IndependentResultCellBuilderError):
        _build(bundle)


def test_rejects_resealed_static_packet_with_foreign_raw_provenance() -> None:
    bundle, _cells = _static_case()
    packet, packet_bytes = _static_packet_source(bundle)
    payload = packet.to_row()
    payload["endpoint_id"] = "foreign_static"
    payload.pop("packet_authority_sha256")
    authority = hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    forged = replace(
        packet,
        endpoint_id="foreign_static",
        packet_authority_sha256=authority,
    )

    with pytest.raises(IndependentResultCellBuilderError):
        _build(bundle, packets=(forged,), packet_bytes=(packet_bytes,))


def test_hostile_packet_digest_cannot_escape_the_error_boundary() -> None:
    bundle, _cells = _static_case()
    packet, packet_bytes = _static_packet_source(bundle)
    sentinel = "must-not-escape-packet-digest"

    class HostileDigest(str):
        def __eq__(self, _other: object) -> bool:
            raise RuntimeError(sentinel)

    poisoned = copy(packet)
    object.__setattr__(
        poisoned,
        "packet_authority_sha256",
        HostileDigest(packet.packet_authority_sha256),
    )

    with pytest.raises(IndependentResultCellBuilderError) as error:
        _build(
            bundle,
            packets=(poisoned,),
            packet_bytes=(packet_bytes,),
            packet_pins=(packet.packet_authority_sha256,),
        )
    assert sentinel not in str(error.value)


def test_global_cell_bound_fails_before_any_cell_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _cells = _static_case()
    packet, packet_bytes = _static_packet_source(bundle)
    allocated = False

    def hostile_build(*_args: object, **_kwargs: object) -> object:
        nonlocal allocated
        allocated = True
        raise AssertionError("must not allocate")

    monkeypatch.setattr(builder_module, "_MAX_RESULT_CELLS", 1)
    monkeypatch.setattr(builder_module.RawNbaApiResultCellV2, "build", hostile_build)
    with pytest.raises(IndependentResultCellBuilderError):
        _build(bundle, packets=(packet,), packet_bytes=(packet_bytes,))
    assert allocated is False


def test_stats_object_index_is_built_once_and_eligibility_precedes_decode() -> None:
    stats_source = inspect.getsource(builder_module._stats_cells)
    build_source = inspect.getsource(builder_module.build_independent_result_cell_authority)

    assert "bundle.objects" not in stats_source
    assert build_source.count("objects_by_sha =") == 1
    assert stats_source.index('landing_disposition == "wide_only"') < stats_source.index(
        "decode_stats_projection_response("
    )


def test_production_builder_has_no_parser_staging_or_dataframe_dependency() -> None:
    source = inspect.getsource(builder_module)
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom))

    assert not any(name.startswith("nbadb.extract") for name in imports)
    assert not any(name.startswith("nbadb.orchestrate") for name in imports)
    assert not any(name.startswith("nbadb.schemas.staging") for name in imports)
    assert "polars" not in imports
