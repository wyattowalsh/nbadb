from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import TYPE_CHECKING

import duckdb
import pytest

from nbadb.contracts import transform_output_materialization_receipt as receipt_module
from nbadb.contracts.transform_output_disposition_authority import (
    CurrentTransformOutputDispositionV1,
    TransformOutputCapabilityPolicyV1,
    TransformOutputEvidenceReferenceV1,
    TransformOutputSemanticClaimV1,
)
from nbadb.contracts.transform_output_materialization_receipt import (
    TransformOutputMaterializationReceiptError,
    TransformOutputMaterializationReceiptV1,
    compile_transform_output_materialization_receipt,
)
from nbadb.orchestrate.successor_transform_authority import (
    TransformOutputAttestation,
    _attest_exact_tables,
)

if TYPE_CHECKING:
    from pathlib import Path


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _entry() -> CurrentTransformOutputDispositionV1:
    evidence = _digest("evidence")
    return CurrentTransformOutputDispositionV1(
        output_name="dim_sample",
        family="dim",
        table_contract_sha256=_digest("contract"),
        schema_identity_sha256=_digest("schema"),
        transform_identity_sha256=_digest("transform"),
        ordered_columns_sha256=_digest("columns"),
        dependency_identity_sha256=_digest("dependencies"),
        state="active",
        capability_policy=TransformOutputCapabilityPolicyV1(
            execute=True,
            primary_materialize=True,
            stable_load=True,
            transform_publication=True,
            chat_ceiling=True,
        ),
        semantic_claims=(
            TransformOutputSemanticClaimV1(
                claim_id="grain",
                claim_kind="grain",
                claim_sha256=_digest("claim"),
                evidence_sha256s=(evidence,),
            ),
        ),
        reason_code="reviewed_active",
        evidence_references=(
            TransformOutputEvidenceReferenceV1(
                evidence_class="executable_test",
                reference_id="test.sample",
                evidence_sha256=evidence,
            ),
        ),
        revalidation_triggers=("contract_change",),
    )


def _attestation(
    *,
    row_count: int = 1,
    schema_sha256: str | None = None,
    content_sha256: str | None = None,
) -> TransformOutputAttestation:
    return TransformOutputAttestation(
        table_name="dim_sample",
        row_count=row_count,
        schema_sha256=schema_sha256 or _digest("physical-schema"),
        content_sha256=content_sha256 or _digest("physical-content"),
    )


def _receipt(
    *,
    entry: CurrentTransformOutputDispositionV1 | None = None,
    attestation: TransformOutputAttestation | None = None,
) -> TransformOutputMaterializationReceiptV1:
    return receipt_module._construct_receipt(
        token=receipt_module._CONSTRUCTION_TOKEN,
        original_materialization_id="transform-run:1:dim_sample",
        transaction_generation_identity_sha256=_digest("transaction-generation"),
        disposition_entry=entry or _entry(),
        materialization_scope="primary_working_duckdb",
        attestation=attestation or _attestation(),
    )


def _real_attestation(
    connection: duckdb.DuckDBPyConnection,
    tmp_path: Path,
) -> TransformOutputAttestation:
    observed = tmp_path.stat()
    return _attest_exact_tables(
        connection,
        ("dim_sample",),
        scratch_parent=tmp_path.resolve(),
        expected_scratch_parent_identity=(observed.st_dev, observed.st_ino),
        transform_scratch_max_bytes=16 * 1024 * 1024,
    )[0]


def test_public_surface_is_parser_only_and_round_trips_canonical_bytes() -> None:
    with pytest.raises(TypeError, match="from_canonical_bytes"):
        TransformOutputMaterializationReceiptV1()
    with pytest.raises(TransformOutputMaterializationReceiptError, match="token"):
        receipt_module._construct_receipt(
            token=object(),
            original_materialization_id="run:1",
            transaction_generation_identity_sha256=_digest("generation"),
            disposition_entry=_entry(),
            materialization_scope="primary_working_duckdb",
            attestation=_attestation(),
        )

    receipt = _receipt()
    encoded = receipt.canonical_bytes()
    assert encoded.endswith(b"\n") and not encoded.endswith(b"\n\n")
    assert (
        TransformOutputMaterializationReceiptV1.from_canonical_bytes(encoded).to_dict()
        == receipt.to_dict()
    )
    assert receipt.receipt_sha256 == receipt_module._digest(receipt._preimage())


def test_public_compiler_fixes_scope_and_exposes_no_digest_override() -> None:
    compiled = compile_transform_output_materialization_receipt(
        original_materialization_id="transform-run:1:dim_sample",
        transaction_generation_identity_sha256=_digest("transaction-generation"),
        disposition_entry=_entry(),
        attestation=_attestation(),
    )

    assert compiled == _receipt()
    assert compiled.materialization_scope == "primary_working_duckdb"
    assert (
        TransformOutputMaterializationReceiptV1.from_canonical_bytes(compiled.canonical_bytes())
        == compiled
    )


def test_public_compiler_rejects_exact_typed_entry_with_mutated_derived_identity() -> None:
    entry = _entry()
    object.__setattr__(entry, "entry_sha256", _digest("forged-entry"))

    with pytest.raises(
        TransformOutputMaterializationReceiptError,
        match="strict replayable authority",
    ):
        compile_transform_output_materialization_receipt(
            original_materialization_id="transform-run:1:dim_sample",
            transaction_generation_identity_sha256=_digest("transaction-generation"),
            disposition_entry=entry,
            attestation=_attestation(),
        )


def test_receipt_is_table_local_and_each_bound_identity_changes_root() -> None:
    baseline = _receipt()
    changed_entry = _receipt(entry=replace(_entry(), schema_identity_sha256=_digest("changed")))
    changed_attestation = _receipt(attestation=_attestation(content_sha256=_digest("changed")))
    assert (
        len(
            {
                baseline.receipt_sha256,
                changed_entry.receipt_sha256,
                changed_attestation.receipt_sha256,
            }
        )
        == 3
    )
    forbidden = {
        "envelope_sha256",
        "proof_pack_sha256",
        "source_bundle_sha256",
        "audit_metadata_sha256",
        "operation_identity_sha256",
        "publication_identity_sha256",
    }
    assert forbidden.isdisjoint(baseline.to_dict())
    assert forbidden.isdisjoint(baseline.disposition_entry.to_dict())


def test_real_attestation_row_reorder_reuses_receipt_but_duplicate_and_schema_drift_do_not(
    tmp_path: Path,
) -> None:
    connection = duckdb.connect()
    try:
        connection.execute("CREATE TABLE dim_sample (id BIGINT, label VARCHAR)")
        connection.execute("INSERT INTO dim_sample VALUES (2, 'b'), (1, 'a')")
        first = _receipt(attestation=_real_attestation(connection, tmp_path))
        connection.execute("DELETE FROM dim_sample")
        connection.execute("INSERT INTO dim_sample VALUES (1, 'a'), (2, 'b')")
        reordered = _receipt(attestation=_real_attestation(connection, tmp_path))
        connection.execute("INSERT INTO dim_sample VALUES (2, 'b')")
        duplicated = _receipt(attestation=_real_attestation(connection, tmp_path))
        connection.execute("DROP TABLE dim_sample")
        connection.execute("CREATE TABLE dim_sample (id DOUBLE, label VARCHAR)")
        connection.execute("INSERT INTO dim_sample VALUES (1.0, 'a'), (2.0, 'b')")
        schema_drift = _receipt(attestation=_real_attestation(connection, tmp_path))
    finally:
        connection.close()

    assert first.receipt_sha256 == reordered.receipt_sha256
    assert duplicated.receipt_sha256 != first.receipt_sha256
    assert schema_drift.receipt_sha256 != first.receipt_sha256


@pytest.mark.parametrize(
    "mutation",
    [
        lambda raw: b" " + raw,
        lambda raw: raw + b"\n",
        lambda raw: raw.replace(b'"kind":', b'"unknown":1,"kind":', 1),
        lambda raw: raw.replace(
            b'"receipt_sha256":', b'"receipt_sha256":"' + (b"0" * 64) + b'","receipt_sha256":', 1
        ),
        lambda _raw: b'{"value":NaN}\n',
    ],
)
def test_noncanonical_unknown_duplicate_and_nonfinite_bytes_fail(
    mutation: object,
) -> None:
    raw = _receipt().canonical_bytes()
    with pytest.raises(TransformOutputMaterializationReceiptError):
        TransformOutputMaterializationReceiptV1.from_canonical_bytes(mutation(raw))  # type: ignore[operator]


def test_mutated_derived_digest_and_wrong_table_fail() -> None:
    payload = json.loads(_receipt().canonical_bytes())
    payload["receipt_sha256"] = _digest("forged")
    with pytest.raises(TransformOutputMaterializationReceiptError, match="not derived"):
        TransformOutputMaterializationReceiptV1.from_canonical_bytes(
            receipt_module._canonical(payload) + b"\n"
        )
    with pytest.raises(TransformOutputMaterializationReceiptError, match="differs"):
        _receipt(attestation=replace(_attestation(), table_name="dim_other"))


@pytest.mark.parametrize("field", ["schema_version", "kind"])
def test_top_level_schema_identity_must_equal_reconstructed_receipt(field: str) -> None:
    payload = json.loads(_receipt().canonical_bytes())
    payload[field] = 2 if field == "schema_version" else "foreign_receipt_kind"
    with pytest.raises(TransformOutputMaterializationReceiptError, match="schema identity"):
        TransformOutputMaterializationReceiptV1.from_canonical_bytes(
            receipt_module._canonical(payload) + b"\n"
        )


def test_parser_bounds_bytes_depth_nodes_and_strings(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _receipt().canonical_bytes()
    with pytest.raises(TransformOutputMaterializationReceiptError, match="oversized"):
        TransformOutputMaterializationReceiptV1.from_canonical_bytes(
            b"x" * (receipt_module._MAX_CANONICAL_BYTES + 1)
        )
    monkeypatch.setattr(receipt_module, "_MAX_DEPTH", 1)
    with pytest.raises(TransformOutputMaterializationReceiptError, match="depth"):
        TransformOutputMaterializationReceiptV1.from_canonical_bytes(raw)
    monkeypatch.setattr(receipt_module, "_MAX_DEPTH", 32)
    monkeypatch.setattr(receipt_module, "_MAX_NODES", 2)
    with pytest.raises(
        TransformOutputMaterializationReceiptError,
        match="aggregate|lexical structure",
    ):
        TransformOutputMaterializationReceiptV1.from_canonical_bytes(raw)
    monkeypatch.setattr(receipt_module, "_MAX_NODES", 16_384)
    monkeypatch.setattr(receipt_module, "_MAX_STRING_BYTES", 2)
    with pytest.raises(
        TransformOutputMaterializationReceiptError,
        match="aggregate|string token",
    ):
        TransformOutputMaterializationReceiptV1.from_canonical_bytes(raw)


@pytest.mark.parametrize(
    ("bound_name", "bound_value", "message"),
    [
        ("_MAX_CANONICAL_BYTES", 32, "canonical byte bound"),
        ("_MAX_DEPTH", 1, "depth bound"),
        ("_MAX_NODES", 2, "aggregate bound"),
        ("_MAX_STRING_BYTES", 2, "aggregate bound"),
    ],
)
def test_private_construction_eagerly_proves_complete_receipt_is_persistable(
    monkeypatch: pytest.MonkeyPatch,
    bound_name: str,
    bound_value: int,
    message: str,
) -> None:
    monkeypatch.setattr(receipt_module, bound_name, bound_value)
    with pytest.raises(TransformOutputMaterializationReceiptError, match=message):
        _receipt()


def test_parser_rejects_over_bound_integer_tokens_before_typed_construction() -> None:
    raw = b'{"row_count":' + (b"1" * (receipt_module._MAX_NUMBER_CHARS + 1)) + b"}\n"
    with pytest.raises(TransformOutputMaterializationReceiptError, match="number token"):
        TransformOutputMaterializationReceiptV1.from_canonical_bytes(raw)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (
            b"[" * (receipt_module._MAX_DEPTH + 1)
            + b"0"
            + b"]" * (receipt_module._MAX_DEPTH + 1)
            + b"\n",
            "lexical depth",
        ),
        (
            b"[" + b",".join([b"0"] * (receipt_module._MAX_NODES + 1)) + b"]\n",
            "lexical structure",
        ),
        (
            b'["' + b"\\u0061" * (receipt_module._MAX_STRING_BYTES // 6 + 1) + b'"]\n',
            "string token",
        ),
        (
            b'["'
            + b"a" * (receipt_module._MAX_STRING_BYTES // 2 + 1)
            + b'","'
            + b"b" * (receipt_module._MAX_STRING_BYTES // 2 + 1)
            + b'"]\n',
            "aggregate string",
        ),
    ],
)
def test_hostile_under_byte_cap_shape_is_rejected_before_json_materialization(
    monkeypatch: pytest.MonkeyPatch,
    raw: bytes,
    message: str,
) -> None:
    assert len(raw) < receipt_module._MAX_CANONICAL_BYTES

    def _must_not_materialize(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("json.loads must not run before lexical rejection")

    monkeypatch.setattr(receipt_module.json, "loads", _must_not_materialize)
    with pytest.raises(TransformOutputMaterializationReceiptError, match=message):
        TransformOutputMaterializationReceiptV1.from_canonical_bytes(raw)


def test_decoder_memory_failure_is_translated(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _receipt().canonical_bytes()

    def _memory_error(*_args: object, **_kwargs: object) -> object:
        raise MemoryError

    monkeypatch.setattr(receipt_module.json, "loads", _memory_error)
    with pytest.raises(TransformOutputMaterializationReceiptError, match="JSON is invalid"):
        TransformOutputMaterializationReceiptV1.from_canonical_bytes(raw)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda: receipt_module._construct_receipt(
            token=receipt_module._CONSTRUCTION_TOKEN,
            original_materialization_id="transform-run:2:dim_sample",
            transaction_generation_identity_sha256=_digest("transaction-generation"),
            disposition_entry=_entry(),
            materialization_scope="primary_working_duckdb",
            attestation=_attestation(),
        ),
        lambda: receipt_module._construct_receipt(
            token=receipt_module._CONSTRUCTION_TOKEN,
            original_materialization_id="transform-run:1:dim_sample",
            transaction_generation_identity_sha256=_digest("different-transaction-generation"),
            disposition_entry=_entry(),
            materialization_scope="primary_working_duckdb",
            attestation=_attestation(),
        ),
        *[
            lambda field=field: _receipt(entry=replace(_entry(), **{field: _digest(field)}))
            for field in (
                "table_contract_sha256",
                "schema_identity_sha256",
                "transform_identity_sha256",
                "ordered_columns_sha256",
                "dependency_identity_sha256",
            )
        ],
        lambda: _receipt(
            entry=replace(
                _entry(),
                state="observed_only_experimental",
                capability_policy=TransformOutputCapabilityPolicyV1(
                    execute=True,
                    primary_materialize=True,
                    stable_load=False,
                    transform_publication=False,
                    chat_ceiling=False,
                ),
            )
        ),
        lambda: _receipt(
            entry=replace(
                _entry(),
                semantic_claims=(
                    replace(_entry().semantic_claims[0], claim_sha256=_digest("changed-claim")),
                ),
            )
        ),
        lambda: _receipt(entry=replace(_entry(), reason_code="reviewed_active_again")),
        lambda: _receipt(
            entry=replace(
                _entry(),
                evidence_references=(
                    replace(
                        _entry().evidence_references[0],
                        reference_id="test.changed-sample",
                    ),
                ),
            )
        ),
        lambda: _receipt(entry=replace(_entry(), revalidation_triggers=("dependency_change",))),
        lambda: _receipt(attestation=_attestation(row_count=2)),
        lambda: _receipt(attestation=_attestation(schema_sha256=_digest("changed-schema"))),
        lambda: _receipt(attestation=_attestation(content_sha256=_digest("changed-content"))),
    ],
)
def test_every_local_identity_and_physical_claim_changes_receipt_root(
    mutation: object,
) -> None:
    assert mutation().receipt_sha256 != _receipt().receipt_sha256  # type: ignore[operator]


def test_output_relabel_requires_a_new_entry_attestation_and_receipt() -> None:
    baseline = _receipt()
    relabeled_entry = replace(_entry(), output_name="dim_relabelled")
    relabeled_attestation = replace(_attestation(), table_name="dim_relabelled")
    relabeled = _receipt(entry=relabeled_entry, attestation=relabeled_attestation)

    assert relabeled.receipt_sha256 != baseline.receipt_sha256
    with pytest.raises(TransformOutputMaterializationReceiptError, match="differs"):
        _receipt(entry=relabeled_entry)


@pytest.mark.parametrize(
    ("path", "field", "value"),
    [
        ((), "schema_version", True),
        ((), "kind", 1),
        (("disposition_entry",), "schema_version", True),
        (("disposition_entry",), "kind", 1),
        (("disposition_entry", "capability_policy"), "schema_version", True),
        (("disposition_entry", "capability_policy"), "kind", 1),
        (("disposition_entry", "semantic_claims", 0), "schema_version", True),
        (("disposition_entry", "semantic_claims", 0), "kind", 1),
        (("disposition_entry", "evidence_references", 0), "schema_version", True),
        (("disposition_entry", "evidence_references", 0), "kind", 1),
    ],
)
def test_schema_and_kind_literals_reject_bool_integer_type_confusion(
    path: tuple[str | int, ...],
    field: str,
    value: object,
) -> None:
    payload: object = json.loads(_receipt().canonical_bytes())
    target = payload
    for segment in path:
        target = target[segment]  # type: ignore[index]
    target[field] = value  # type: ignore[index]
    with pytest.raises(TransformOutputMaterializationReceiptError, match="schema identity"):
        TransformOutputMaterializationReceiptV1.from_canonical_bytes(
            receipt_module._canonical(payload) + b"\n"
        )
