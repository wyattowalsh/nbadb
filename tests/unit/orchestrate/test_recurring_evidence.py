from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from nbadb.orchestrate.recurring_evidence import (
    REQUIRED_DOCS_PARITY_SURFACES,
    REQUIRED_HUMAN_COVERAGE_CATEGORIES,
    DataGreenReceiptV1,
    DocsMetadataParityV1,
    ExactParentSuccessorV1,
    FreshnessDecision,
    FullBaselineProvenanceV1,
    HumanFormatObservationV1,
    HumanQueryObservationV1,
    HumanVerificationReceiptV1,
    ImmutableVersionReadbackV1,
    ReadbackResourceV1,
    RecurringEvidenceError,
    RecurringRunPhase,
    RecurringRunStatusReason,
    RecurringRunStatusV1,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


SOURCE_SHA = hashlib.sha1(b"reviewed source", usedforsecurity=False).hexdigest()
DATASET_REF = "trusted-owner/nbadb"
PARENT_VERSION = 41
SUCCESSOR_VERSION = 42
PARENT_FINGERPRINT = _sha("parent fingerprint")
TRANSACTION_ID = _sha("stable update transaction")
CANDIDATE_ID = _sha("assured candidate")
COORDINATOR_ID = _sha("coordinator")
REQUEST_UNIVERSE = _sha("request universe")
REMOTE_READBACK = _sha("successor remote readback")
PUBLICATION_RECEIPT = _sha("successor publication receipt")
SOURCE_CI = _sha("exact source CI")
UPSTREAM_AUTHORITY = _sha("upstream authority")
MODEL_AUTHORITY = _sha("model authority")


def _inventory_sha(resources: tuple[ReadbackResourceV1, ...]) -> str:
    encoded = json.dumps(
        [item.to_dict() for item in resources],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _fresh_status() -> RecurringRunStatusV1:
    return RecurringRunStatusV1(
        source_sha=SOURCE_SHA,
        actions_run_id=9001,
        actions_run_attempt=1,
        expected_prior_nba_date="2026-08-25",
        timezone="America/New_York",
        provider_availability_cutoff="2026-08-26T10:00:00Z",
        scheduled_deadline="2026-08-26T12:00:00Z",
        actual_completion="2026-08-26T11:30:00Z",
        phase=RecurringRunPhase.COMPLETE,
        freshness=FreshnessDecision.FRESH,
        reason=RecurringRunStatusReason.UPDATE_PUBLISHED_AND_READ_BACK,
        dataset_ref=DATASET_REF,
        parent_dataset_version=PARENT_VERSION,
        parent_cutoff="2026-08-25T09:00:00Z",
        parent_fingerprint_sha256=PARENT_FINGERPRINT,
        latest_assured_remote_version=SUCCESSOR_VERSION,
        latest_assured_remote_cutoff="2026-08-26T09:00:00Z",
        update_transaction_id=TRANSACTION_ID,
        coordinator_identity_sha256=COORDINATOR_ID,
        candidate_identity_sha256=CANDIDATE_ID,
        request_closure_sha256=REQUEST_UNIVERSE,
        publication_readback_sha256=REMOTE_READBACK,
        provider_mutation_count=12,
        kaggle_mutation_count=1,
        no_mutation_proven=False,
        no_mutation_proof_sha256=None,
    )


def _early_failure_status() -> RecurringRunStatusV1:
    return RecurringRunStatusV1(
        source_sha=SOURCE_SHA,
        actions_run_id=9002,
        actions_run_attempt=1,
        expected_prior_nba_date="2026-08-25",
        timezone="America/New_York",
        provider_availability_cutoff="2026-08-26T10:00:00Z",
        scheduled_deadline="2026-08-26T12:00:00Z",
        actual_completion="2026-08-26T10:02:00Z",
        phase=RecurringRunPhase.PRE_EXTRACTION,
        freshness=FreshnessDecision.NOT_FRESH,
        reason=RecurringRunStatusReason.PARENT_ADMISSION_FAILED,
        dataset_ref=DATASET_REF,
        parent_dataset_version=None,
        parent_cutoff=None,
        parent_fingerprint_sha256=None,
        latest_assured_remote_version=None,
        latest_assured_remote_cutoff=None,
        update_transaction_id=None,
        coordinator_identity_sha256=None,
        candidate_identity_sha256=None,
        request_closure_sha256=None,
        publication_readback_sha256=None,
        provider_mutation_count=0,
        kaggle_mutation_count=0,
        no_mutation_proven=True,
        no_mutation_proof_sha256=_sha("early failure no mutation"),
    )


def _resources() -> tuple[ReadbackResourceV1, ...]:
    return tuple(
        ReadbackResourceV1(
            path=path,
            size_bytes=index * 100,
            declared_sha256=_sha(path),
            streamed_sha256=_sha(path),
        )
        for index, path in enumerate(
            (
                "csv/fact_game.csv",
                "nba.duckdb",
                "nba.sqlite",
                "parquet/fact_game.parquet",
            ),
            start=1,
        )
    )


def _readback() -> ImmutableVersionReadbackV1:
    resources = _resources()
    return ImmutableVersionReadbackV1(
        dataset_ref=DATASET_REF,
        parent_dataset_version=PARENT_VERSION,
        dataset_version=SUCCESSOR_VERSION,
        version_endpoint=f"/{DATASET_REF}/versions/{SUCCESSOR_VERSION}",
        source_sha=SOURCE_SHA,
        update_transaction_id=TRANSACTION_ID,
        parent_fingerprint_sha256=PARENT_FINGERPRINT,
        assured_candidate_sha256=CANDIDATE_ID,
        publication_receipt_sha256=PUBLICATION_RECEIPT,
        remote_publication_readback_sha256=REMOTE_READBACK,
        resources=resources,
        resource_inventory_sha256=_inventory_sha(resources),
        dataset_root_id="immutable-dataset-root-42",
        evidence_root_id="separate-evidence-root-42",
        immutable_tree_sha256_before=_sha("immutable tree"),
        immutable_tree_sha256_after=_sha("immutable tree"),
    )


def _query(format_name: str) -> HumanQueryObservationV1:
    return HumanQueryObservationV1(
        query_id=f"{format_name}_sample",
        query_sha256=_sha(f"{format_name} query"),
        result_sha256=_sha(f"{format_name} result"),
        row_count=2,
        sampled_value_sha256s=(_sha(f"{format_name} value"),),
    )


def _format_observations() -> tuple[HumanFormatObservationV1, ...]:
    definitions = (
        ("duckdb", "read_only_external_access_disabled", ("nba.duckdb",)),
        ("sqlite", "mode_ro_immutable_1", ("nba.sqlite",)),
        (
            "parquet",
            "independent_decoder_read_only",
            ("parquet/fact_game.parquet",),
        ),
        ("csv", "independent_decoder_read_only", ("csv/fact_game.csv",)),
    )
    return tuple(
        HumanFormatObservationV1(
            format_name=format_name,
            access_mode=access_mode,
            decoder_identity_sha256=_sha(f"{format_name} decoder"),
            sampled_resource_paths=paths,
            query_observations=(_query(format_name),),
        )
        for format_name, access_mode, paths in definitions
    )


def _human(readback: ImmutableVersionReadbackV1 | None = None) -> HumanVerificationReceiptV1:
    readback = readback or _readback()
    return HumanVerificationReceiptV1(
        dataset_ref=DATASET_REF,
        parent_dataset_version=PARENT_VERSION,
        successor_dataset_version=SUCCESSOR_VERSION,
        source_sha=SOURCE_SHA,
        update_transaction_id=TRANSACTION_ID,
        parent_fingerprint_sha256=PARENT_FINGERPRINT,
        assured_candidate_sha256=CANDIDATE_ID,
        immutable_readback_sha256=readback.content_sha256,
        resource_inventory_sha256=readback.resource_inventory_sha256,
        immutable_tree_sha256_before=readback.immutable_tree_sha256_before,
        immutable_tree_sha256_after=readback.immutable_tree_sha256_after,
        challenge_sha256=_sha("human challenge"),
        challenge_nonce="manual-nonce-0123456789abcdef0123456789abcdef",
        coverage_categories=REQUIRED_HUMAN_COVERAGE_CATEGORIES,
        verifier_subject="github:wyatt",
        verifier_identity_sha256=_sha("human identity"),
        authentication_method="github_trusted_handoff",
        authentication_evidence_sha256=_sha("authentication evidence"),
        trusted_handoff_receipt_sha256=_sha("trusted handoff"),
        audit_time="2026-08-26T15:00:00Z",
        format_observations=_format_observations(),
        version_page_inventory_sha256=readback.resource_inventory_sha256,
        acknowledgement=(
            "I manually verified the exact immutable nbadb version in all four formats."
        ),
    )


def _docs(
    readback: ImmutableVersionReadbackV1 | None = None,
    human: HumanVerificationReceiptV1 | None = None,
) -> DocsMetadataParityV1:
    readback = readback or _readback()
    human = human or _human(readback)
    return DocsMetadataParityV1(
        dataset_ref=DATASET_REF,
        parent_dataset_version=PARENT_VERSION,
        successor_dataset_version=SUCCESSOR_VERSION,
        source_sha=SOURCE_SHA,
        model_authority_sha256=MODEL_AUTHORITY,
        update_transaction_id=TRANSACTION_ID,
        assured_candidate_sha256=CANDIDATE_ID,
        immutable_readback_sha256=readback.content_sha256,
        human_verification_receipt_sha256=human.content_sha256,
        remote_resource_inventory_sha256=readback.resource_inventory_sha256,
        stable_registry_sha256=_sha("stable registry"),
        authored_docs_sha256=_sha("authored docs"),
        generated_schema_sha256=_sha("generated schema"),
        generated_lineage_sha256=_sha("generated lineage"),
        generated_catalog_sha256=_sha("generated catalog"),
        kaggle_metadata_sha256=_sha("kaggle metadata"),
        cadence_contract_sha256=_sha("cadence contract"),
        temporal_contract_sha256=_sha("temporal contract"),
        provenance_contract_sha256=_sha("provenance contract"),
        limitations_sha256=_sha("limitations"),
        experimental_labels_sha256=_sha("experimental labels"),
        parity_evidence_sha256=_sha("docs parity evidence"),
        checked_surfaces=REQUIRED_DOCS_PARITY_SURFACES,
    )


def _baseline() -> FullBaselineProvenanceV1:
    return FullBaselineProvenanceV1(
        dataset_ref=DATASET_REF,
        dataset_version=PARENT_VERSION,
        source_sha=SOURCE_SHA,
        upstream_authority_sha256=UPSTREAM_AUTHORITY,
        model_authority_sha256=MODEL_AUTHORITY,
        model_green_receipt_sha256=_sha("model green"),
        actions_run_id=8001,
        actions_run_attempt=1,
        extraction_chain_id="full-model-baseline-chain",
        free_execution_admission_sha256=_sha("baseline free admission"),
        source_ci_receipt_sha256=SOURCE_CI,
        full_extraction_receipt_sha256=_sha("full extraction"),
        committed_checkpoint_sha256=_sha("committed checkpoint"),
        terminal_catchup_sha256=_sha("terminal catchup"),
        terminal_scan_sha256=_sha("terminal scan"),
        four_format_parity_sha256=_sha("baseline four format parity"),
        dynamic_resource_inventory_sha256=_sha("baseline inventory"),
        initial_remote_resource_inventory_sha256=_sha("baseline inventory"),
        initial_assurance_sha256=_sha("initial assurance"),
        publication_ledger_receipt_sha256=_sha("initial ledger"),
        initial_remote_readback_sha256=_sha("initial remote readback"),
        public_version_fingerprint_sha256=PARENT_FINGERPRINT,
    )


def _successor(status: RecurringRunStatusV1 | None = None) -> ExactParentSuccessorV1:
    status = status or _fresh_status()
    return ExactParentSuccessorV1(
        dataset_ref=DATASET_REF,
        parent_dataset_version=PARENT_VERSION,
        successor_dataset_version=SUCCESSOR_VERSION,
        source_sha=SOURCE_SHA,
        upstream_authority_sha256=UPSTREAM_AUTHORITY,
        model_authority_sha256=MODEL_AUTHORITY,
        source_ci_receipt_sha256=SOURCE_CI,
        update_transaction_id=TRANSACTION_ID,
        parent_fingerprint_sha256=PARENT_FINGERPRINT,
        assured_candidate_sha256=CANDIDATE_ID,
        update_assurance_sha256=_sha("update assurance"),
        recurring_run_status=status,
        recurring_run_status_sha256=status.content_sha256,
        coordinator_identity_sha256=COORDINATOR_ID,
        request_universe_sha256=REQUEST_UNIVERSE,
        monthly_acceptance_sha256=_sha("monthly acceptance"),
        opportunistic_acceptance_sha256=_sha("opportunistic acceptance"),
        four_format_parity_sha256=_sha("successor four format parity"),
        dynamic_resource_inventory_sha256=_inventory_sha(_resources()),
        free_execution_admission_sha256=_sha("successor free admission"),
        publication_intent_sha256=_sha("publication intent"),
        transaction_generation_resource_sha256=_sha("transaction generation resource"),
        publication_ledger_receipt_sha256=_sha("successor ledger"),
        publication_receipt_sha256=PUBLICATION_RECEIPT,
        remote_publication_readback_sha256=REMOTE_READBACK,
        remote_resource_inventory_sha256=_inventory_sha(_resources()),
    )


def _data_green() -> DataGreenReceiptV1:
    baseline = _baseline()
    successor = _successor()
    readback = _readback()
    human = _human(readback)
    docs = _docs(readback, human)
    return DataGreenReceiptV1(
        source_sha=SOURCE_SHA,
        upstream_authority_sha256=UPSTREAM_AUTHORITY,
        model_authority_sha256=MODEL_AUTHORITY,
        dataset_ref=DATASET_REF,
        initial_dataset_version=PARENT_VERSION,
        successor_dataset_version=SUCCESSOR_VERSION,
        update_transaction_id=TRANSACTION_ID,
        baseline=baseline,
        baseline_provenance_sha256=baseline.content_sha256,
        successor=successor,
        exact_parent_successor_sha256=successor.content_sha256,
        immutable_readback=readback,
        immutable_readback_sha256=readback.content_sha256,
        human_verification=human,
        human_verification_sha256=human.content_sha256,
        docs_metadata_parity=docs,
        docs_metadata_parity_sha256=docs.content_sha256,
        initial_publication_readback_sha256=baseline.initial_remote_readback_sha256,
        successor_publication_readback_sha256=successor.remote_publication_readback_sha256,
        external_rights_receipt_sha256=_sha("external rights"),
        actions_closeout_run_id=9100,
        actions_closeout_run_attempt=1,
        closeout_job_receipt_sha256=_sha("closeout job"),
        closeout_source_ci_receipt_sha256=SOURCE_CI,
    )


@pytest.mark.parametrize(
    "receipt",
    [
        pytest.param(_fresh_status(), id="fresh-status"),
        pytest.param(_early_failure_status(), id="early-failure-status"),
        pytest.param(_readback(), id="immutable-readback"),
        pytest.param(_human(), id="human-verification"),
        pytest.param(_docs(), id="docs-parity"),
        pytest.param(_baseline(), id="full-baseline"),
        pytest.param(_successor(), id="exact-parent-successor"),
        pytest.param(_data_green(), id="data-green"),
    ],
)
def test_canonical_receipts_round_trip_exactly(receipt: object) -> None:
    receipt_type = type(receipt)
    decoded_dict = receipt_type.from_dict(receipt.to_dict())
    decoded_bytes = receipt_type.from_bytes(receipt.canonical_bytes)

    assert decoded_dict == receipt
    assert decoded_bytes == receipt
    assert decoded_bytes.canonical_bytes == receipt.canonical_bytes
    assert decoded_bytes.content_sha256 == receipt.content_sha256


def test_pre_extraction_failure_is_always_finalized_with_no_mutation_proof() -> None:
    receipt = _early_failure_status()

    assert receipt.freshness is FreshnessDecision.NOT_FRESH
    assert receipt.parent_dataset_version is None
    assert receipt.update_transaction_id is None
    assert receipt.no_mutation_proven is True
    assert receipt.provider_mutation_count == 0
    assert receipt.kaggle_mutation_count == 0


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"no_mutation_proven": False}, "no-mutation"),
        ({"provider_mutation_count": 1}, "conflicts with mutation counts"),
        ({"candidate_identity_sha256": CANDIDATE_ID}, "cannot bind a candidate"),
        ({"parent_dataset_version": True}, "positive integer"),
        ({"finalizer_always_ran": False}, "always finalizer"),
    ],
)
def test_pre_extraction_status_rejects_false_or_invented_state(
    changes: dict[str, object], match: str
) -> None:
    with pytest.raises(RecurringEvidenceError, match=match):
        replace(_early_failure_status(), **changes)


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"kaggle_mutation_count": 0}, "exactly one Kaggle mutation"),
        ({"latest_assured_remote_version": PARENT_VERSION}, "newer remote version"),
        ({"request_closure_sha256": None}, "missing terminal evidence"),
        ({"freshness": FreshnessDecision.NOT_FRESH}, "conflicts with not_fresh"),
        ({"latest_assured_remote_cutoff": "2026-08-24T00:00:00Z"}, "expected day"),
    ],
)
def test_fresh_status_rejects_incomplete_or_stale_evidence(
    changes: dict[str, object], match: str
) -> None:
    with pytest.raises(RecurringEvidenceError, match=match):
        replace(_fresh_status(), **changes)


@pytest.mark.parametrize(
    "path",
    ["../nba.duckdb", "/nba.duckdb", "data//nba.duckdb", "data/./nba.duckdb", "C:/nba.duckdb"],
)
def test_resource_rejects_unsafe_or_noncanonical_paths(path: str) -> None:
    with pytest.raises(RecurringEvidenceError, match="canonical relative POSIX path"):
        ReadbackResourceV1(
            path=path,
            size_bytes=1,
            declared_sha256=_sha("resource"),
            streamed_sha256=_sha("resource"),
        )


def test_resource_rejects_bool_size_symlink_and_stream_digest_drift() -> None:
    base = _resources()[0]
    with pytest.raises(RecurringEvidenceError, match="nonnegative integer"):
        replace(base, size_bytes=True)
    with pytest.raises(RecurringEvidenceError, match="never symlinks"):
        replace(base, file_type="symlink")
    with pytest.raises(RecurringEvidenceError, match="differs from declaration"):
        replace(base, streamed_sha256=_sha("different bytes"))
    with pytest.raises(RecurringEvidenceError, match="signed-63-bit range"):
        replace(base, size_bytes=1 << 63)
    with pytest.raises(RecurringEvidenceError, match="valid Unicode"):
        replace(base, path="\ud800")


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"version_endpoint": f"/{DATASET_REF}/versions/latest"}, "exact /versions/N"),
        ({"dataset_root_id": "separate-evidence-root-42"}, "roots must be separate"),
        ({"immutable_tree_sha256_after": _sha("changed tree")}, "tree changed"),
        ({"dataset_tree_non_writable": False}, "non_writable=true"),
        ({"sidecars_absent": False}, "sidecars_absent=true"),
        ({"dataset_version": SUCCESSOR_VERSION + 1}, "exact next parent successor"),
        ({"resource_inventory_sha256": _sha("wrong inventory")}, "digest drifted"),
    ],
)
def test_immutable_readback_fails_closed(changes: dict[str, object], match: str) -> None:
    with pytest.raises(RecurringEvidenceError, match=match):
        replace(_readback(), **changes)


def test_immutable_readback_rejects_duplicate_and_unsorted_paths() -> None:
    readback = _readback()
    duplicate = (*readback.resources, readback.resources[-1])
    with pytest.raises(RecurringEvidenceError, match="sorted and path-unique"):
        replace(
            readback,
            resources=duplicate,
            resource_inventory_sha256=_inventory_sha(duplicate),
        )
    reversed_resources = tuple(reversed(readback.resources))
    with pytest.raises(RecurringEvidenceError, match="sorted and path-unique"):
        replace(
            readback,
            resources=reversed_resources,
            resource_inventory_sha256=_inventory_sha(reversed_resources),
        )


def test_readback_from_dict_rejects_bool_counts_and_inventory_count_drift() -> None:
    payload = _readback().to_dict()
    payload["resource_count"] = True
    with pytest.raises(RecurringEvidenceError, match="nonnegative integer"):
        ImmutableVersionReadbackV1.from_dict(payload)

    payload = _readback().to_dict()
    payload["resource_count"] = len(_resources()) + 1
    with pytest.raises(RecurringEvidenceError, match="does not match inventory"):
        ImmutableVersionReadbackV1.from_dict(payload)


def test_human_receipt_requires_every_format_and_manual_samples() -> None:
    human = _human()
    with pytest.raises(RecurringEvidenceError, match="all four formats"):
        replace(human, format_observations=human.format_observations[:-1])
    with pytest.raises(RecurringEvidenceError, match="storage format"):
        replace(
            human.format_observations[0],
            sampled_resource_paths=("nba.sqlite",),
        )
    with pytest.raises(RecurringEvidenceError, match="must be nonempty"):
        replace(_query("duckdb"), sampled_value_sha256s=())


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"verifier_subject": "workflow_bot"}, "human identity"),
        ({"authentication_method": "default_success"}, "trusted human method"),
        ({"workflow_authored": True}, "automation cannot author"),
        ({"headless": True}, "automation cannot author"),
        ({"human_authored": False}, "human_authored=true"),
        ({"version_page_inventory_sha256": _sha("other inventory")}, "version-page"),
        ({"immutable_tree_sha256_after": _sha("changed tree")}, "changed the immutable"),
        ({"coverage_categories": REQUIRED_HUMAN_COVERAGE_CATEGORIES[:-1]}, "required inventory"),
    ],
)
def test_human_receipt_rejects_automated_or_incomplete_attestation(
    changes: dict[str, object], match: str
) -> None:
    with pytest.raises(RecurringEvidenceError, match=match):
        replace(_human(), **changes)


def test_docs_parity_requires_all_surfaces_and_zero_mismatches() -> None:
    docs = _docs()
    with pytest.raises(RecurringEvidenceError, match="required inventory"):
        replace(docs, checked_surfaces=docs.checked_surfaces[:-1])
    with pytest.raises(RecurringEvidenceError, match="unresolved mismatches"):
        replace(docs, mismatch_codes=("cadence_drift",))
    with pytest.raises(RecurringEvidenceError, match="must be complete"):
        replace(docs, parity_complete=False)


def test_exact_successor_rejects_status_or_parent_mixups() -> None:
    successor = _successor()
    with pytest.raises(RecurringEvidenceError, match="status digest drifted"):
        replace(successor, recurring_run_status_sha256=_sha("wrong status"))
    with pytest.raises(RecurringEvidenceError, match="does not close"):
        replacement_status = replace(
            successor.recurring_run_status,
            candidate_identity_sha256=_sha("other candidate"),
        )
        replace(
            successor,
            recurring_run_status=replacement_status,
            recurring_run_status_sha256=replacement_status.content_sha256,
        )
    with pytest.raises(RecurringEvidenceError, match="exact next version"):
        replace(successor, successor_dataset_version=SUCCESSOR_VERSION + 1)
    with pytest.raises(RecurringEvidenceError, match="frozen candidate inventory"):
        replace(successor, dynamic_resource_inventory_sha256=_sha("different inventory"))


def test_full_baseline_rejects_remote_inventory_drift() -> None:
    with pytest.raises(RecurringEvidenceError, match="frozen baseline inventory"):
        replace(
            _baseline(),
            initial_remote_resource_inventory_sha256=_sha("different inventory"),
        )


def test_data_green_join_requires_every_exact_constituent() -> None:
    receipt = _data_green()

    with pytest.raises(RecurringEvidenceError, match="drifted from its constituent"):
        replace(receipt, immutable_readback_sha256=_sha("wrong immutable receipt"))
    with pytest.raises(RecurringEvidenceError, match="update_transaction_id differs"):
        other_transaction = _sha("other transaction")
        human = replace(receipt.human_verification, update_transaction_id=other_transaction)
        replace(
            receipt,
            human_verification=human,
            human_verification_sha256=human.content_sha256,
        )
    with pytest.raises(RecurringEvidenceError, match="candidate identity differs"):
        human = replace(
            receipt.human_verification,
            assured_candidate_sha256=_sha("other candidate"),
        )
        replace(
            receipt,
            human_verification=human,
            human_verification_sha256=human.content_sha256,
        )
    with pytest.raises(RecurringEvidenceError, match="mixes versions or parents"):
        baseline = replace(receipt.baseline, dataset_version=PARENT_VERSION - 1)
        replace(
            receipt,
            baseline=baseline,
            baseline_provenance_sha256=baseline.content_sha256,
        )
    with pytest.raises(RecurringEvidenceError, match="requires all_proofs_complete=true"):
        replace(receipt, all_proofs_complete=False)
    with pytest.raises(RecurringEvidenceError, match="requires data_green=true"):
        replace(receipt, data_green=False)


def test_data_green_rejects_human_sample_outside_immutable_inventory() -> None:
    receipt = _data_green()
    first_format = replace(
        receipt.human_verification.format_observations[0],
        sampled_resource_paths=("unknown.duckdb",),
    )
    human = replace(
        receipt.human_verification,
        format_observations=(
            first_format,
            *receipt.human_verification.format_observations[1:],
        ),
    )
    docs = replace(
        receipt.docs_metadata_parity,
        human_verification_receipt_sha256=human.content_sha256,
    )
    with pytest.raises(RecurringEvidenceError, match="outside the immutable readback"):
        replace(
            receipt,
            human_verification=human,
            human_verification_sha256=human.content_sha256,
            docs_metadata_parity=docs,
            docs_metadata_parity_sha256=docs.content_sha256,
        )


def test_data_green_from_dict_rejects_missing_proof_and_bool_as_int() -> None:
    payload = _data_green().to_dict()
    del payload["human_verification"]
    with pytest.raises(RecurringEvidenceError, match="missing=.*human_verification"):
        DataGreenReceiptV1.from_dict(payload)

    payload = _data_green().to_dict()
    payload["initial_dataset_version"] = True
    with pytest.raises(RecurringEvidenceError, match="positive integer"):
        DataGreenReceiptV1.from_dict(payload)


def test_canonical_codec_rejects_duplicate_keys_and_noncanonical_bytes() -> None:
    receipt = _fresh_status()
    duplicate = receipt.canonical_bytes.replace(
        b'{"actions_run_attempt":1,',
        b'{"actions_run_attempt":1,"actions_run_attempt":1,',
        1,
    )
    with pytest.raises(RecurringEvidenceError, match="duplicate key"):
        RecurringRunStatusV1.from_bytes(duplicate)

    pretty = json.dumps(receipt.to_dict(), indent=2, sort_keys=True).encode() + b"\n"
    with pytest.raises(RecurringEvidenceError, match="not the canonical JSON encoding"):
        RecurringRunStatusV1.from_bytes(pretty)

    without_newline = receipt.canonical_bytes.removesuffix(b"\n")
    with pytest.raises(RecurringEvidenceError, match="not the canonical JSON encoding"):
        RecurringRunStatusV1.from_bytes(without_newline)


@pytest.mark.parametrize(
    "receipt_type, receipt",
    [
        (RecurringRunStatusV1, _fresh_status()),
        (ImmutableVersionReadbackV1, _readback()),
        (HumanVerificationReceiptV1, _human()),
        (DocsMetadataParityV1, _docs()),
        (DataGreenReceiptV1, _data_green()),
    ],
)
def test_top_level_codecs_reject_boolean_schema_versions(
    receipt_type: type[object], receipt: object
) -> None:
    payload = receipt.to_dict()
    payload["schema_version"] = True
    with pytest.raises(RecurringEvidenceError, match="schema identity"):
        receipt_type.from_dict(payload)
