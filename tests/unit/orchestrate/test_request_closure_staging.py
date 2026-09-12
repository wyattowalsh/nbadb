from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.core.errors import ParserInputCaptureIntegrityError
from nbadb.extract.bronze import LogicalCallReceiptBinding
from nbadb.orchestrate.staging_batches import (
    StagingBatchStore,
    StagingChunkMetadata,
    StagingFrameBatch,
)

_ROUTE = "fixture_endpoint:stg_fixture_result:0"


def _binding(*, route_ids: tuple[str, ...] = (_ROUTE,)) -> LogicalCallReceiptBinding:
    return LogicalCallReceiptBinding(
        logical_call_receipt_sha256="a" * 64,
        endpoint_name="fixture_endpoint",
        logical_parameters_sha256="b" * 64,
        provider_authority_sha256="c" * 64,
        result_route_ids=route_ids,
    )


def _metadata() -> StagingChunkMetadata:
    return StagingChunkMetadata(
        run_mode="init",
        lane_id="init.fixture",
        pattern="season",
        chunk_index=0,
        params_digest="chunk-params",
        entries_digest="fixture-entry",
        source_endpoint_name="fixture_endpoint",
        source_params_digest="source-params",
    )


def _batch(binding: LogicalCallReceiptBinding) -> StagingFrameBatch:
    return StagingFrameBatch(
        frames={"stg_fixture_result": pl.DataFrame({"value": [1, 2]})},
        metadata=_metadata(),
        expected_staging_keys=("stg_fixture_result",),
        receipt_binding=binding,
        result_route_ids_by_staging_key=(("stg_fixture_result", _ROUTE),),
    )


def test_read_after_commit_returns_exact_logical_route_receipt() -> None:
    conn = duckdb.connect(":memory:")
    try:
        store = StagingBatchStore(conn)
        binding = _binding()
        store.persist_frame_batches((_batch(binding),), materialize=False)

        receipts = store.committed_logical_call_receipts(binding)
    finally:
        conn.close()

    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt.result_route_id == _ROUTE
    assert receipt.staging_key == "stg_fixture_result"
    assert receipt.persisted_row_count == 2
    assert receipt.logical_call_receipt_sha256 == binding.logical_call_receipt_sha256
    assert len(receipt.receipt_root_sha256) == 64


def test_read_after_commit_rejects_incomplete_route_inventory() -> None:
    conn = duckdb.connect(":memory:")
    try:
        store = StagingBatchStore(conn)
        persisted_binding = _binding()
        store.persist_frame_batches((_batch(persisted_binding),), materialize=False)
        widened_binding = _binding(route_ids=(_ROUTE, "fixture_endpoint:stg_fixture_second:1"))

        with pytest.raises(ParserInputCaptureIntegrityError, match="exactly cover"):
            store.committed_logical_call_receipts(widened_binding)
    finally:
        conn.close()


def test_caller_owned_transaction_cannot_self_attest_before_commit() -> None:
    conn = duckdb.connect(":memory:")
    try:
        store = StagingBatchStore(conn)
        binding = _binding()
        with store.existing_transaction_writer() as writer:
            conn.execute("BEGIN TRANSACTION")
            writer.persist_frame_batches((_batch(binding),), materialize=False)
            with pytest.raises(ParserInputCaptureIntegrityError, match="caller-owned"):
                store.committed_logical_call_receipts(binding)
            conn.execute("ROLLBACK")
    finally:
        conn.close()
