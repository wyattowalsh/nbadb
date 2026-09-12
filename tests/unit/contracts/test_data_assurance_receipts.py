from __future__ import annotations

import json

import pytest

from nbadb.contracts.data_assurance_receipts import (
    DATA_ASSURANCE_SCHEMA_VERSION,
    DataAssuranceReceiptError,
    DataGreenReceiptV1,
    DocsMetadataParityV1,
    HumanObservationV1,
    HumanQueryCheckV1,
    HumanVerificationChallengeV1,
    HumanVerificationReceiptV1,
    PrepublicationDataAdmissionV1,
    PrivateCaptureAssuranceReceiptV1,
    RemotePrivateExclusionScanV1,
    RemoteReadbackReceiptV1,
    RemoteResourceV1,
    RemoteSchemaObservationV1,
    RemoteValueQueryObservationV1,
)

_GIT_SHA = "1" * 40
_DIGIT = "a" * 64
_OTHER_DIGIT = "b" * 64


def _resource(path: str = "data/dim_game.parquet") -> RemoteResourceV1:
    return RemoteResourceV1(
        canonical_path=path,
        size_bytes=128,
        sha256=_DIGIT,
        media_type="application/octet-stream",
    )


def _schema_observation(relation: str = "dim_game") -> RemoteSchemaObservationV1:
    return RemoteSchemaObservationV1(
        relation_name=relation,
        ordered_columns=("game_id", "game_date"),
        physical_types=("VARCHAR", "DATE"),
        row_count=1234,
    )


def _value_observation(query_id: str = "q1") -> RemoteValueQueryObservationV1:
    return RemoteValueQueryObservationV1(query_id=query_id, result_sha256=_DIGIT, result_rows=5)


def _exclusion_scan(private_hits: int = 0) -> RemotePrivateExclusionScanV1:
    return RemotePrivateExclusionScanV1(
        scope="public-candidate",
        scanned_paths=300,
        private_hits=private_hits,
        scan_sha256=_DIGIT,
    )


def _private_capture() -> PrivateCaptureAssuranceReceiptV1:
    return PrivateCaptureAssuranceReceiptV1.build(
        chain_id="chain-1",
        source_sha=_GIT_SHA,
        generation=2,
        private_checkpoint_database_sha256=_DIGIT,
        private_checkpoint_report_sha256=_DIGIT,
        parser_input_inventory_sha256=_DIGIT,
        request_observation_inventory_sha256=_DIGIT,
        result_occurrence_inventory_sha256=_DIGIT,
        route_landing_inventory_sha256=_DIGIT,
        response_body_inventory_sha256=_DIGIT,
        declared_bodyless_inventory_sha256=_DIGIT,
        capture_digest=_DIGIT,
        conservation_digest=_DIGIT,
        reconstruction_digest=_DIGIT,
        route_closure_digest=_DIGIT,
        w2_input_digest=_DIGIT,
        private_resource_count=12,
        private_resource_bytes=4096,
    )


def _prepublication() -> PrepublicationDataAdmissionV1:
    return PrepublicationDataAdmissionV1.build(
        chain_id="chain-1",
        source_sha=_GIT_SHA,
        generation=2,
        private_capture_receipt_sha256=_private_capture().receipt_sha256,
        public_disposition_sha256=_DIGIT,
        candidate_inventory_sha256=_DIGIT,
        candidate_tree_sha256=_DIGIT,
        committed_checkpoint_transaction_sha256=_DIGIT,
        checkpoint_database_sha256=_DIGIT,
        checkpoint_report_sha256=_DIGIT,
        assured_manifest_sha256=_DIGIT,
        terminal_report_sha256=_DIGIT,
        metadata_sha256=_DIGIT,
        admitted=True,
    )


def _readback(
    *,
    private_hits: int = 0,
    parity_ok: bool = True,
    resources: tuple[RemoteResourceV1, ...] | None = None,
    private_exclusion_scan: tuple[RemotePrivateExclusionScanV1, ...] | None = None,
) -> RemoteReadbackReceiptV1:
    return RemoteReadbackReceiptV1.build(
        dataset="owner/dataset",
        dataset_version=7,
        source_sha=_GIT_SHA,
        chain_id="chain-1",
        terminal_handoff_sha256=_DIGIT,
        public_disposition_sha256=_DIGIT,
        prepublication_admission_sha256=_DIGIT,
        publication_intent_sha256=_DIGIT,
        publication_marker_sha256=_DIGIT,
        resources=resources
        if resources is not None
        else (_resource(), _resource("data/dim_player.parquet")),
        remote_inventory_sha256=_DIGIT,
        remote_tree_sha256=_DIGIT,
        schema_observations=(_schema_observation(), _schema_observation("dim_player")),
        value_query_observations=(_value_observation(), _value_observation("q2")),
        private_exclusion_scan=private_exclusion_scan
        if private_exclusion_scan is not None
        else (_exclusion_scan(private_hits),),
        readback_fingerprint=_DIGIT,
        parity_ok=parity_ok,
    )


def _query(query_id: str = "q1", expected: str = _DIGIT) -> HumanQueryCheckV1:
    return HumanQueryCheckV1(
        query_id=query_id,
        query_text="SELECT count(*) FROM dim_game",
        formats=("duckdb", "sqlite"),
        expected_result_sha256=expected,
    )


def _challenge(expected: str = _DIGIT) -> HumanVerificationChallengeV1:
    return HumanVerificationChallengeV1.build(
        readback_receipt_sha256=_DIGIT,
        dataset_version=7,
        nonce="nonce-123",
        issued_at="2026-09-06T00:00:00+00:00",
        queries=(_query("q1", expected), _query("q2", expected)),
        required_acknowledgment_text="I verified these results myself.",
    )


def _human_receipt(
    *,
    observed: str = _DIGIT,
    matches: bool | None = None,
    nonce: str = "nonce-123",
    acknowledgment: str = "I verified these results myself.",
    failures: tuple[str, ...] | None = None,
    observations: tuple[HumanObservationV1, ...] | None = None,
) -> HumanVerificationReceiptV1:
    def _flag() -> bool:
        if matches is None:
            return observed == _DIGIT
        return matches

    built = observations or (
        HumanObservationV1(
            query_id="q1", observed_result_sha256=observed, matches_expected=_flag()
        ),
        HumanObservationV1(
            query_id="q2", observed_result_sha256=observed, matches_expected=_flag()
        ),
    )
    if failures is None:
        failures = tuple(
            sorted(
                observation.query_id for observation in built if not observation.matches_expected
            )
        )
    return HumanVerificationReceiptV1.build(
        challenge_sha256=_challenge().challenge_sha256,
        readback_receipt_sha256=_DIGIT,
        dataset_version=7,
        nonce=nonce,
        verified_actor="human-operator",
        observed_at="2026-09-06T01:00:00+00:00",
        observations=built,
        failures=failures,
        acknowledgment=acknowledgment,
    )


def _docs_parity() -> DocsMetadataParityV1:
    return DocsMetadataParityV1.build(
        source_sha=_GIT_SHA,
        metadata_child_sha256=None,
        uploaded_metadata_sha256=_DIGIT,
        uploaded_metadata_projection_sha256=_DIGIT,
        observed_publication_sha256=None,
        authored_docs_inventory_sha256=_DIGIT,
        generated_docs_inventory_sha256=_DIGIT,
        remote_readback_receipt_sha256=_DIGIT,
        parity=True,
    )


def _data_green(model_status: str = "GREEN") -> DataGreenReceiptV1:
    return DataGreenReceiptV1.build(
        dataset="owner/dataset",
        dataset_version=7,
        source_sha=_GIT_SHA,
        chain_id="chain-1",
        private_capture_receipt_sha256=_DIGIT,
        public_disposition_sha256=_DIGIT,
        prepublication_admission_sha256=_DIGIT,
        terminal_handoff_sha256=_DIGIT,
        publication_intent_sha256=_DIGIT,
        publication_execution_sha256=_DIGIT,
        publication_resolution_sha256=_DIGIT,
        remote_readback_receipt_sha256=_DIGIT,
        human_verification_receipt_sha256=_DIGIT,
        docs_metadata_parity_sha256=_DIGIT,
        model_status=model_status,
        data_status="GREEN",
    )


_ALL_RECEIPTS = pytest.mark.parametrize(
    "builder",
    [
        _private_capture,
        _prepublication,
        _readback,
        _challenge,
        _human_receipt,
        _docs_parity,
        _data_green,
    ],
    ids=lambda builder: builder.__name__.lstrip("_"),
)


class TestEvidenceItems:
    def test_resource_rejects_bad_paths_and_digests(self) -> None:
        with pytest.raises(DataAssuranceReceiptError, match="relative POSIX"):
            _resource("/abs/path")
        with pytest.raises(DataAssuranceReceiptError, match="traversal|segments|relative"):
            _resource("a/../../b")
        with pytest.raises(DataAssuranceReceiptError, match="sha256"):
            RemoteResourceV1("data/x", 1, "zz", "application/json")

    def test_schema_observation_rejects_length_mismatch(self) -> None:
        with pytest.raises(DataAssuranceReceiptError, match="equal length"):
            RemoteSchemaObservationV1("dim_game", ("a", "b"), ("VARCHAR",), 1)

    def test_query_check_rejects_unknown_format(self) -> None:
        with pytest.raises(DataAssuranceReceiptError, match="formats"):
            HumanQueryCheckV1("q1", "SELECT 1", ("excel",), _DIGIT)


class TestSealing:
    @_ALL_RECEIPTS
    def test_round_trip_through_json(self, builder) -> None:
        receipt = builder()
        payload = receipt.to_payload()
        encoded = json.dumps(payload, sort_keys=True)
        restored = type(receipt).from_payload(json.loads(encoded))
        assert restored == receipt
        assert restored.to_payload() == payload

    @_ALL_RECEIPTS
    def test_payload_carries_schema_version(self, builder) -> None:
        assert builder().to_payload()["schema_version"] == DATA_ASSURANCE_SCHEMA_VERSION

    @_ALL_RECEIPTS
    def test_digest_substitution_fails(self, builder) -> None:
        receipt = builder()
        payload = receipt.to_payload()
        digest_field = type(receipt)._DIGEST_FIELD
        payload[digest_field] = "c" * 64
        with pytest.raises(DataAssuranceReceiptError, match="digest mismatch"):
            type(receipt).from_payload(payload)

    @_ALL_RECEIPTS
    def test_wrong_join_fails(self, builder) -> None:
        receipt = builder()
        payload = receipt.to_payload()
        # Swap any non-digest sha256 binding; the recomputed self digest then
        # disagrees, proving joins are digest-covered.
        swapped = False
        for key, value in payload.items():
            if isinstance(value, str) and len(value) == 64 and value == "a" * 64:
                payload[key] = _OTHER_DIGIT
                swapped = True
                break
        assert swapped, "fixture must contain a swappable digest binding"
        with pytest.raises(DataAssuranceReceiptError, match="digest mismatch"):
            type(receipt).from_payload(payload)

    @_ALL_RECEIPTS
    def test_extra_and_missing_keys_fail(self, builder) -> None:
        receipt = builder()
        payload = receipt.to_payload()
        extra = {**payload, "surprise": 1}
        with pytest.raises(DataAssuranceReceiptError, match="extra=\\['surprise'\\]"):
            type(receipt).from_payload(extra)
        missing = dict(payload)
        removed = sorted(key for key in missing if key != "schema_version")[0]
        del missing[removed]
        with pytest.raises(DataAssuranceReceiptError, match="missing"):
            type(receipt).from_payload(missing)

    @_ALL_RECEIPTS
    def test_build_requires_exact_keys(self, builder) -> None:
        receipt = builder()
        payload = receipt.to_payload()
        del payload["schema_version"]
        del payload[type(receipt)._DIGEST_FIELD]
        with pytest.raises(DataAssuranceReceiptError, match="keys mismatch"):
            type(receipt).build(**{**payload, "unexpected": None})

    @_ALL_RECEIPTS
    def test_build_is_deterministic(self, builder) -> None:
        assert builder() == builder()

    @_ALL_RECEIPTS
    def test_verify_revalidates(self, builder) -> None:
        builder().verify()


class TestPrivateCapture:
    def test_rejects_body_bytes(self) -> None:
        with pytest.raises(DataAssuranceReceiptError, match="sha256"):
            PrivateCaptureAssuranceReceiptV1.build(
                chain_id="chain-1",
                source_sha=_GIT_SHA,
                generation=1,
                private_checkpoint_database_sha256=b"raw bytes",
                private_checkpoint_report_sha256=_DIGIT,
                parser_input_inventory_sha256=_DIGIT,
                request_observation_inventory_sha256=_DIGIT,
                result_occurrence_inventory_sha256=_DIGIT,
                route_landing_inventory_sha256=_DIGIT,
                response_body_inventory_sha256=_DIGIT,
                declared_bodyless_inventory_sha256=_DIGIT,
                capture_digest=_DIGIT,
                conservation_digest=_DIGIT,
                reconstruction_digest=_DIGIT,
                route_closure_digest=_DIGIT,
                w2_input_digest=_DIGIT,
                private_resource_count=1,
                private_resource_bytes=1,
            )

    def test_rejects_zero_generation_and_bad_source_sha(self) -> None:
        base = _private_capture()
        payload = base.to_payload()
        payload["generation"] = 0
        del payload["schema_version"]
        del payload["receipt_sha256"]
        with pytest.raises(DataAssuranceReceiptError, match="generation"):
            PrivateCaptureAssuranceReceiptV1.build(**payload)
        payload["generation"] = 1
        payload["source_sha"] = "nothex"
        with pytest.raises(DataAssuranceReceiptError, match="git sha"):
            PrivateCaptureAssuranceReceiptV1.build(**payload)


class TestPrepublication:
    def test_admitted_false_is_a_contradiction(self) -> None:
        payload = _prepublication().to_payload()
        payload["admitted"] = False
        del payload["schema_version"]
        del payload["admission_sha256"]
        with pytest.raises(DataAssuranceReceiptError, match="admitted"):
            PrepublicationDataAdmissionV1.build(**payload)


class TestReadback:
    def test_private_hits_with_parity_true_fails(self) -> None:
        with pytest.raises(DataAssuranceReceiptError, match="parity_ok"):
            _readback(private_hits=1, parity_ok=True)

    def test_clean_scan_with_parity_false_fails(self) -> None:
        with pytest.raises(DataAssuranceReceiptError, match="parity_ok"):
            _readback(private_hits=0, parity_ok=False)

    def test_duplicate_resource_paths_fail(self) -> None:
        duplicate = _resource("data/dim_game.parquet")
        with pytest.raises(DataAssuranceReceiptError, match="unique"):
            _readback(resources=(duplicate, duplicate))

    def test_empty_vectors_fail(self) -> None:
        with pytest.raises(DataAssuranceReceiptError, match="not be empty"):
            _readback(resources=())
        with pytest.raises(DataAssuranceReceiptError, match="not be empty"):
            _readback(private_exclusion_scan=())


class TestHumanVerification:
    def test_challenge_is_deterministic(self) -> None:
        assert _challenge() == _challenge()
        assert _challenge().challenge_sha256 != _challenge(expected=_OTHER_DIGIT).challenge_sha256

    def test_automation_acknowledgment_rejected(self) -> None:
        with pytest.raises(DataAssuranceReceiptError, match="human-authored"):
            _human_receipt(acknowledgment="AUTOMATED")
        # Whitespace-only text strips to the empty sentinel and is rejected the
        # same way rather than passing as a genuine acknowledgment.
        with pytest.raises(DataAssuranceReceiptError, match="human-authored"):
            _human_receipt(acknowledgment="  ")

    def test_validate_against_challenge_accepts_genuine_receipt(self) -> None:
        _human_receipt().validate_against_challenge(_challenge())

    def test_validate_rejects_derived_disagreement(self) -> None:
        # Observed hash differs from expected while matches_expected claims True.
        receipt = _human_receipt(observed=_OTHER_DIGIT, matches=True)
        with pytest.raises(DataAssuranceReceiptError, match="matches_expected"):
            receipt.validate_against_challenge(_challenge())

    def test_validate_recomputes_failures(self) -> None:
        receipt = _human_receipt(observed=_OTHER_DIGIT, matches=False, failures=())
        with pytest.raises(DataAssuranceReceiptError, match="failures"):
            receipt.validate_against_challenge(_challenge())

    def test_validate_rejects_wrong_nonce_and_acknowledgment(self) -> None:
        receipt = _human_receipt(nonce="nonce-999")
        with pytest.raises(DataAssuranceReceiptError, match="nonce"):
            receipt.validate_against_challenge(_challenge())

    def test_validate_rejects_incomplete_coverage(self) -> None:
        receipt = _human_receipt(
            observations=(
                HumanObservationV1(
                    query_id="q1", observed_result_sha256=_DIGIT, matches_expected=True
                ),
            )
        )
        with pytest.raises(DataAssuranceReceiptError, match="query matrix"):
            receipt.validate_against_challenge(_challenge())


class TestDocsParity:
    def test_optional_child_fields_accept_none_and_valid_sha(self) -> None:
        base = _docs_parity()
        payload = base.to_payload()
        payload["metadata_child_sha256"] = "2" * 40
        del payload["schema_version"]
        del payload["parity_sha256"]
        parity = DocsMetadataParityV1.build(**payload)
        assert parity.metadata_child_sha256 == "2" * 40
        payload["observed_publication_sha256"] = "not-a-sha"
        with pytest.raises(DataAssuranceReceiptError, match="git sha"):
            DocsMetadataParityV1.build(**payload)

    def test_parity_false_is_a_contradiction(self) -> None:
        payload = _docs_parity().to_payload()
        payload["parity"] = False
        del payload["schema_version"]
        del payload["parity_sha256"]
        with pytest.raises(DataAssuranceReceiptError, match="parity"):
            DocsMetadataParityV1.build(**payload)


class TestDataGreen:
    def test_model_red_does_not_block(self) -> None:
        receipt = _data_green(model_status="RED")
        assert receipt.model_status == "RED"
        assert receipt.data_status == "GREEN"
        receipt.verify()

    def test_data_status_literal_is_derived(self) -> None:
        payload = _data_green().to_payload()
        payload["data_status"] = "AMBER"
        del payload["schema_version"]
        del payload["data_green_sha256"]
        with pytest.raises(DataAssuranceReceiptError, match="data_status"):
            DataGreenReceiptV1.build(**payload)

    def test_unknown_model_status_fails(self) -> None:
        payload = _data_green().to_payload()
        payload["model_status"] = "YELLOW"
        del payload["schema_version"]
        del payload["data_green_sha256"]
        with pytest.raises(DataAssuranceReceiptError, match="model_status"):
            DataGreenReceiptV1.build(**payload)

    @pytest.mark.parametrize(
        "missing",
        [
            "remote_readback_receipt_sha256",
            "human_verification_receipt_sha256",
            "docs_metadata_parity_sha256",
            "publication_resolution_sha256",
        ],
    )
    def test_incomplete_chain_cannot_build(self, missing: str) -> None:
        payload = _data_green().to_payload()
        del payload["schema_version"]
        del payload["data_green_sha256"]
        del payload[missing]
        with pytest.raises(DataAssuranceReceiptError, match="keys mismatch"):
            DataGreenReceiptV1.build(**payload)

    def test_missing_chain_digests_rejected_as_values(self) -> None:
        payload = _data_green().to_payload()
        payload["human_verification_receipt_sha256"] = ""
        del payload["schema_version"]
        del payload["data_green_sha256"]
        with pytest.raises(DataAssuranceReceiptError, match="human_verification"):
            DataGreenReceiptV1.build(**payload)
