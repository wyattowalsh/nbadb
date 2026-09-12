"""Focused production-composition tests for one W2 source-call candidate."""

from __future__ import annotations

from copy import copy
from dataclasses import replace
from functools import cache
from typing import Any, cast

import duckdb
import polars as pl
import pytest

from nbadb.contracts.value_projection_equality import ValueProjectionEqualityReceiptV1
from nbadb.extract.bronze import LogicalCallReceiptBinding
from nbadb.orchestrate import w2_source_call_builder as builder_module
from nbadb.orchestrate.public_value_authority_store import PublicValueAuthorityStore
from nbadb.orchestrate.raw_request_store import RawRequestAuthorityStore
from nbadb.orchestrate.staging_batches import CommittedStagingFrameReadbackV2
from nbadb.orchestrate.w2_operation_coordinator import (
    W2SourceCallCandidateV1,
    coordinate_w2_source_call,
)
from nbadb.orchestrate.w2_operation_store import W2OperationStore
from nbadb.orchestrate.w2_source_call_builder import (
    W2SourceCallBuilderError,
    build_w2_source_call_candidate,
)
from tests.unit.contracts.test_public_value_authority_adapter import _live_bundle
from tests.unit.contracts.test_raw_request_authority import (
    _static_bundle,
    _stats_fallback_bundle,
    _video_bundle,
)
from tests.unit.contracts.test_raw_result_cell_authority import _stats_case
from tests.unit.contracts.test_value_projection_plan_builder import _packet_source
from tests.unit.contracts.test_w2_operation_builder import (
    _source_values,
    _static_packet_bytes,
    _valid_values,
)


def _binding(values: dict[str, object]) -> LogicalCallReceiptBinding:
    bundle = cast("Any", values["raw_bundle"])
    selected = tuple(item for item in bundle.observations if item.lifecycle == "selected_terminal")
    assert len(selected) == 1
    observation = selected[0]
    routes = tuple(
        sorted(
            item.route_id
            for item in bundle.landings
            if item.observation_sha256 == observation.attempt.observation_sha256
        )
    )
    return LogicalCallReceiptBinding(
        logical_call_receipt_sha256=observation.logical_receipt_sha256,
        endpoint_name=routes[0].split(":", 1)[0],
        logical_parameters_sha256=observation.attempt.safe_parameters_sha256,
        provider_authority_sha256=observation.attempt.provider_authority_sha256,
        result_route_ids=routes,
    )


def _candidate_from_values(
    connection: duckdb.DuckDBPyConnection,
    *,
    values: dict[str, object],
    changes: dict[str, object] | None = None,
) -> W2SourceCallCandidateV1:
    bundle = cast("Any", values["raw_bundle"])
    raw_receipt = RawRequestAuthorityStore(connection).persist_bundle(bundle)
    arguments: dict[str, object] = {
        "logical_call_binding": _binding(values),
        "raw_authority_persistence_receipt": raw_receipt,
        "expected_raw_authority_persistence_receipt_sha256": raw_receipt.receipt_sha256,
        "raw_bundle": bundle,
        "expected_raw_authority_bundle_sha256": bundle.bundle_sha256,
        "committed_staging_readbacks": values["committed_staging_readbacks"],
        "expected_committed_staging_readback_sha256s": values[
            "expected_committed_staging_readback_sha256s"
        ],
        "body_blob_inventory": values["body_blob_inventory"],
        "expected_body_blob_inventory_sha256": values["expected_body_blob_inventory_sha256"],
        "body_blob_inventory_readback_receipt": values["body_blob_inventory_readback_receipt"],
        "expected_body_blob_inventory_readback_receipt_sha256": values[
            "expected_body_blob_inventory_readback_receipt_sha256"
        ],
        "declared_bodyless_packets": values["declared_bodyless_packets"],
        "expected_declared_bodyless_packet_authority_sha256s": values[
            "expected_declared_bodyless_packet_authority_sha256s"
        ],
        "declared_bodyless_readback_receipts": values["declared_bodyless_readback_receipts"],
        "expected_declared_bodyless_readback_receipt_sha256s": values[
            "expected_declared_bodyless_readback_receipt_sha256s"
        ],
        "declared_bodyless_packet_bytes": values["declared_bodyless_packet_bytes"],
        "route_landing_receipts": values["route_landing_receipts"],
        "expected_route_landing_receipt_sha256s": values["expected_route_landing_receipt_sha256s"],
        "canonical_alias_receipts": values["canonical_alias_receipts"],
        "expected_canonical_alias_receipt_sha256s": values[
            "expected_canonical_alias_receipt_sha256s"
        ],
    }
    if changes:
        arguments.update(changes)
    return build_w2_source_call_candidate(**cast("Any", arguments))


def _candidate(
    connection: duckdb.DuckDBPyConnection,
    *,
    changes: dict[str, object] | None = None,
) -> W2SourceCallCandidateV1:
    return _candidate_from_values(
        connection,
        values=dict(_valid_values()),
        changes=changes,
    )


@cache
def _branch_values(case: str) -> dict[str, object]:
    if case == "stats":
        bundle, _cells = _stats_case()
        return _source_values(bundle)
    if case == "missing_result":
        bundle, *_rest = _stats_fallback_bundle("missing_result")
        return _source_values(bundle)
    if case == "alias":
        bundle, *_rest = _video_bundle(
            "VideoEvents",
            {"future": {"x": [1, "two"]}},
        )
        return _source_values(bundle)
    if case == "live":
        return _source_values(_live_bundle())
    if case == "static":
        bundle, observation, _occurrence, _landing = _static_bundle()
        packet, readback = _packet_source(observation)
        packet_bytes = _static_packet_bytes(observation.attempt.endpoint_id)
        return _source_values(
            bundle,
            packets=(packet,),
            bodyless_readbacks=(readback,),
            packet_bytes=(packet_bytes,),
        )
    raise AssertionError(f"unknown source branch: {case}")


def test_derives_every_w2_child_and_coordinates_one_durable_admission() -> None:
    connection = duckdb.connect(":memory:")
    candidate = _candidate(connection)

    assert type(candidate) is W2SourceCallCandidateV1
    inputs = candidate.operation_inputs
    assert (
        inputs.expected_raw_authority_bundle_sha256 == cast("Any", inputs.raw_bundle).bundle_sha256
    )
    assert (
        inputs.expected_ownership_receipt_sha256
        == cast("Any", inputs.ownership_receipt).receipt_sha256
    )
    assert inputs.expected_plan_sha256 == cast("Any", inputs.plan).plan_sha256
    assert (
        inputs.expected_body_projection_sha256
        == cast("Any", inputs.body_projection).projection_sha256
    )
    assert (
        inputs.expected_public_projection_sha256
        == cast("Any", inputs.public_projection).projection_sha256
    )
    assert (
        inputs.expected_value_projection_equality_receipt_sha256
        == cast("Any", inputs.value_projection_equality_receipt).receipt_sha256
    )

    admission = coordinate_w2_source_call(
        candidate,
        public_value_store=PublicValueAuthorityStore(connection),
        operation_store=W2OperationStore(connection),
    )

    assert admission.logical_call_receipt_sha256 == (
        candidate.logical_call_binding.logical_call_receipt_sha256
    )
    assert admission.raw_authority_bundle_sha256 == inputs.expected_raw_authority_bundle_sha256
    assert admission.operation_receipt_sha256 == admission.operation.operation_receipt_sha256


@pytest.mark.parametrize("case", ("stats", "missing_result", "live", "static", "alias"))
def test_derives_each_body_source_and_route_alias_branch(case: str) -> None:
    connection = duckdb.connect(":memory:")
    candidate = _candidate_from_values(
        connection,
        values=dict(_branch_values(case)),
    )
    inputs = candidate.operation_inputs

    assert candidate.logical_call_binding.endpoint_name
    assert cast("Any", inputs.raw_bundle).bundle_sha256 == (
        inputs.expected_raw_authority_bundle_sha256
    )
    assert cast("Any", inputs.value_projection_equality_receipt).receipt_sha256 == (
        inputs.expected_value_projection_equality_receipt_sha256
    )
    if case == "stats":
        assert len(cast("tuple[object, ...]", inputs.result_cell_rows)) > 0
    elif case == "missing_result":
        assert cast("tuple[object, ...]", inputs.result_cell_rows) == ()
        assert len(cast("tuple[object, ...]", inputs.stats_lossless_rows)) > 0
    elif case == "live":
        assert len(cast("tuple[object, ...]", inputs.live_lossless_rows)) > 0
        assert cast("tuple[object, ...]", inputs.stats_lossless_rows) == ()
    elif case == "static":
        assert len(cast("tuple[object, ...]", inputs.declared_bodyless_packets)) == 1
        assert len(cast("tuple[object, ...]", inputs.result_cell_rows)) > 0
    else:
        assert len(cast("tuple[object, ...]", inputs.canonical_alias_receipts)) > 0
        assert len(cast("tuple[object, ...]", inputs.route_field_landing_rows)) > 0


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "expected_raw_authority_bundle_sha256",
            "f" * 64,
            "Raw Authority V2 bundle failed exact replay",
        ),
        (
            "expected_committed_staging_readback_sha256s",
            (),
            "bounded exact tuple",
        ),
        (
            "expected_body_blob_inventory_sha256",
            "e" * 64,
            "failed exact pin replay",
        ),
    ],
)
def test_rejects_changed_external_source_pins_before_candidate_build(
    field: str,
    value: object,
    message: str,
) -> None:
    connection = duckdb.connect(":memory:")

    with pytest.raises(W2SourceCallBuilderError, match=message):
        _candidate(connection, changes={field: value})


def test_rejects_foreign_outer_types_and_secret_inventory_containers() -> None:
    connection = duckdb.connect(":memory:")

    with pytest.raises(W2SourceCallBuilderError, match="logical-call binding"):
        _candidate(connection, changes={"logical_call_binding": object()})
    with pytest.raises(W2SourceCallBuilderError, match="known-secret inventory"):
        _candidate(connection, changes={"known_secrets": []})


@pytest.mark.parametrize(
    "known_secrets",
    (
        (b"",),
        (b"x" * 4_097,),
        ("\ud800",),
        (b"x",) * 129,
    ),
)
def test_rejects_empty_over_bound_and_non_utf8_secret_inventories(
    known_secrets: tuple[str | bytes, ...],
) -> None:
    with pytest.raises(W2SourceCallBuilderError, match="known-secret inventory"):
        _candidate(
            duckdb.connect(":memory:"),
            changes={"known_secrets": known_secrets},
        )


def test_all_external_container_bounds_run_before_any_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def observe_child(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return object()

    monkeypatch.setattr(
        builder_module,
        "build_independent_result_cell_authority",
        observe_child,
    )
    monkeypatch.setattr(builder_module, "MAX_AUTHORITY_ROWS", 0)
    with pytest.raises(W2SourceCallBuilderError, match="bounded exact tuple"):
        _candidate(duckdb.connect(":memory:"))
    assert calls == 0


def test_declared_bodyless_packet_bytes_have_item_and_aggregate_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb.connect(":memory:")
    monkeypatch.setattr(builder_module, "MAX_DECLARED_BODYLESS_PACKET_BYTES", 1)
    with pytest.raises(W2SourceCallBuilderError, match="over-bound payload"):
        _candidate(
            connection,
            changes={"declared_bodyless_packet_bytes": (b"{}",)},
        )

    monkeypatch.setattr(builder_module, "MAX_DECLARED_BODYLESS_PACKET_BYTES", 64)
    monkeypatch.setattr(builder_module, "_MAX_INT64", 1)
    with pytest.raises(W2SourceCallBuilderError, match="cumulative byte bound"):
        _candidate(
            connection,
            changes={"declared_bodyless_packet_bytes": (b"{}",)},
        )


def test_rejects_empty_duplicate_and_reordered_staging_readbacks() -> None:
    connection = duckdb.connect(":memory:")
    values = dict(_valid_values())
    first = cast(
        "tuple[CommittedStagingFrameReadbackV2, ...]",
        values["committed_staging_readbacks"],
    )[0]

    with pytest.raises(W2SourceCallBuilderError, match="bounded exact tuple"):
        _candidate(
            connection,
            changes={
                "committed_staging_readbacks": (),
                "expected_committed_staging_readback_sha256s": (),
            },
        )
    with pytest.raises(W2SourceCallBuilderError, match="repeats one identity"):
        _candidate(
            connection,
            changes={
                "committed_staging_readbacks": (first, first),
                "expected_committed_staging_readback_sha256s": (
                    first.readback_receipt_sha256,
                    first.readback_receipt_sha256,
                ),
            },
        )

    second_receipt = replace(
        first.committed_receipt,
        chunk_id="chunk:w2-source-call-builder-second",
    )
    second = CommittedStagingFrameReadbackV2.build(
        committed_receipt=second_receipt,
        frame=pl.DataFrame(),
    )
    pins = (first.readback_receipt_sha256, second.readback_receipt_sha256)
    _candidate(
        connection,
        changes={
            "committed_staging_readbacks": (first, second),
            "expected_committed_staging_readback_sha256s": pins,
        },
    )
    with pytest.raises(W2SourceCallBuilderError, match="duplicated or reordered"):
        _candidate(
            connection,
            changes={
                "committed_staging_readbacks": (second, first),
                "expected_committed_staging_readback_sha256s": pins,
            },
        )


def test_replays_logical_binding_raw_persistence_and_staging_dtos() -> None:
    connection = duckdb.connect(":memory:")
    values = dict(_valid_values())
    binding = _binding(values)
    with pytest.raises(W2SourceCallBuilderError, match="logical-call binding failed"):
        _candidate(
            connection,
            changes={"logical_call_binding": replace(binding, endpoint_name="foreign_endpoint")},
        )

    bundle = cast("Any", values["raw_bundle"])
    receipt = RawRequestAuthorityStore(connection).persist_bundle(bundle)
    forged_receipt = copy(receipt)
    object.__setattr__(forged_receipt, "object_count", receipt.object_count + 1)
    with pytest.raises(W2SourceCallBuilderError, match="failed exact bundle replay"):
        _candidate(
            connection,
            changes={
                "raw_authority_persistence_receipt": forged_receipt,
                "expected_raw_authority_persistence_receipt_sha256": (
                    forged_receipt.receipt_sha256
                ),
            },
        )

    readback = cast(
        "tuple[CommittedStagingFrameReadbackV2, ...]",
        values["committed_staging_readbacks"],
    )[0]
    forged_readback = copy(readback)
    object.__setattr__(
        forged_readback,
        "canonical_frame_size_bytes",
        readback.canonical_frame_size_bytes + 1,
    )
    with pytest.raises(W2SourceCallBuilderError, match="failed exact DTO replay"):
        _candidate(
            connection,
            changes={"committed_staging_readbacks": (forged_readback,)},
        )


@pytest.mark.parametrize(
    "producer_name",
    (
        "build_independent_result_cell_authority",
        "build_independent_stats_lossless_authorities",
        "build_live_lossless_value_authority",
        "build_public_value_ownership_authority",
        "build_value_projection_plan",
        "build_raw_nba_api_route_field_landing_authority",
        "build_public_table_value_projection",
        "build_independent_body_value_projection",
    ),
)
def test_sanitizes_every_child_producer_error(
    monkeypatch: pytest.MonkeyPatch,
    producer_name: str,
) -> None:
    def hostile(*_args: object, **_kwargs: object) -> object:
        raise W2SourceCallBuilderError("SECRET_CANARY")

    monkeypatch.setattr(builder_module, producer_name, hostile)
    with pytest.raises(W2SourceCallBuilderError, match="derivation failed") as exc_info:
        _candidate(duckdb.connect(":memory:"))
    assert "SECRET_CANARY" not in str(exc_info.value)


@pytest.mark.parametrize(
    "producer_name",
    (
        "build_independent_result_cell_authority",
        "build_independent_stats_lossless_authorities",
        "build_live_lossless_value_authority",
        "build_public_value_ownership_authority",
        "build_value_projection_plan",
        "build_raw_nba_api_route_field_landing_authority",
        "build_public_table_value_projection",
        "build_independent_body_value_projection",
    ),
)
def test_rejects_foreign_child_returns_before_member_access(
    monkeypatch: pytest.MonkeyPatch,
    producer_name: str,
) -> None:
    monkeypatch.setattr(
        builder_module,
        producer_name,
        lambda *_args, **_kwargs: object(),
    )
    with pytest.raises(W2SourceCallBuilderError, match="foreign|DTO"):
        _candidate(duckdb.connect(":memory:"))


def test_reconstructs_exact_child_clones_and_rejects_hostile_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supplied = copy(_valid_values()["result_cell_authority_receipt"])
    monkeypatch.setattr(
        builder_module,
        "build_independent_result_cell_authority",
        lambda *_args, **_kwargs: supplied,
    )
    candidate = _candidate(duckdb.connect(":memory:"))
    retained = candidate.operation_inputs.result_cell_authority_receipt
    assert retained == supplied
    assert retained is not supplied

    class HostileDigest:
        def __eq__(self, _other: object) -> bool:
            raise W2SourceCallBuilderError("SECRET_CANARY")

    forged = copy(supplied)
    object.__setattr__(forged, "authority_sha256", HostileDigest())
    monkeypatch.setattr(
        builder_module,
        "build_independent_result_cell_authority",
        lambda *_args, **_kwargs: forged,
    )
    with pytest.raises(W2SourceCallBuilderError, match="exact DTO replay") as exc_info:
        _candidate(duckdb.connect(":memory:"))
    assert "SECRET_CANARY" not in str(exc_info.value)


def test_equality_child_return_is_sanitized_and_exactly_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def hostile_build(*_args: object, **_kwargs: object) -> object:
        raise W2SourceCallBuilderError("SECRET_CANARY")

    monkeypatch.setattr(ValueProjectionEqualityReceiptV1, "build", hostile_build)
    with pytest.raises(W2SourceCallBuilderError, match="derivation failed") as exc_info:
        _candidate(duckdb.connect(":memory:"))
    assert "SECRET_CANARY" not in str(exc_info.value)

    monkeypatch.setattr(
        ValueProjectionEqualityReceiptV1,
        "build",
        classmethod(lambda _cls, **_kwargs: object()),
    )
    with pytest.raises(W2SourceCallBuilderError, match="foreign exact DTO"):
        _candidate(duckdb.connect(":memory:"))
