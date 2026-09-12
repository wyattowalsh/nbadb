from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import pandera.errors
import polars as pl
import pytest

from nbadb.contracts import raw_live_plan_authority
from nbadb.contracts.raw_live_plan_authority import (
    LIVE_PLAN_KIND,
    GenerationKind,
    LiveObservationPlanBindingV2,
    LivePlanCallAdmissionV2,
    LivePlanGenerationReceiptV2,
    RawLivePlanAuthorityError,
    validate_live_observation_plan_authority,
    validate_live_plan_authority_tables,
)
from nbadb.contracts.raw_request_finalization import finalize_raw_request_capture
from nbadb.schemas.raw.nba_api_live_plan import (
    RawNbaApiLivePlanCallAdmissionSchema,
    RawNbaApiLivePlanGenerationReceiptSchema,
    RawNbaApiObservationLivePlanSchema,
)
from tests.unit.contracts.test_raw_request_finalization import (
    _STARTED_AT,
    _case,
    _live_plan_authority,
)

if TYPE_CHECKING:
    from nbadb.contracts.raw_request_authority import (
        RawRequestAuthorityBundleV2,
        RequestAttemptIdentityV2,
    )
    from nbadb.contracts.raw_request_reconstruction import LiveSnapshotPlanAuthorityV2

type LiveCase = tuple[
    LivePlanGenerationReceiptV2,
    LivePlanCallAdmissionV2,
    LiveObservationPlanBindingV2,
    RawRequestAuthorityBundleV2,
    LiveSnapshotPlanAuthorityV2,
]

_EXTERNAL_RECEIPT = "e" * 64
_AUTHORIZATION_RECEIPT = "a" * 64
_AUTHORIZATION_COLLECTOR = "c" * 64


class _SplitUtcDatetime(datetime):
    def isoformat(self, *args: object, **kwargs: object) -> str:
        return "2099-01-01T00:00:00+00:00"


def _sha(value: str | bytes) -> str:
    encoded = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _plan_item(
    attempt: RequestAttemptIdentityV2,
    route_ids: tuple[str, ...],
    *,
    ordinal: int = 0,
) -> dict[str, object]:
    return {
        "chain_id": attempt.chain_id,
        "endpoint_contract_sha256": attempt.endpoint_contract_sha256,
        "endpoint_id": attempt.endpoint_id,
        "lane_id": attempt.lane_id,
        "logical_invocation_sha256": attempt.logical_invocation_sha256,
        "plan_item_ordinal": ordinal,
        "provider_authority_sha256": attempt.provider_authority_sha256,
        "provider_call_sha256": attempt.provider_call_sha256,
        "route_ids": list(route_ids),
        "run_attempt": attempt.run_attempt,
        "run_id": attempt.run_id,
        "safe_parameters_sha256": attempt.safe_parameters_sha256,
        "scope_sha256": attempt.scope_sha256,
        "semantic_request_sha256": attempt.semantic_request_sha256,
        "source_sha": attempt.source_sha,
    }


def _plan_bytes(
    attempt: RequestAttemptIdentityV2,
    route_ids: tuple[str, ...],
    *,
    root_updates: dict[str, object] | None = None,
    item_updates: dict[str, object] | None = None,
) -> bytes:
    item = _plan_item(attempt, route_ids)
    if item_updates:
        item.update(item_updates)
    root: dict[str, object] = {
        "items": [item],
        "kind": LIVE_PLAN_KIND,
        "schema_version": 2,
    }
    if root_updates:
        root.update(root_updates)
    return _canonical(root)


def _generation(
    attempt: RequestAttemptIdentityV2,
    *,
    sealed_plan_bytes: bytes,
    generation_kind: GenerationKind = "full_root",
    parent_generation_receipt_sha256: str | None = None,
    parent_capture_root_sha256: str | None = None,
    external_receipt_sha256: str = _EXTERNAL_RECEIPT,
    matrix_lane_id: str | None = None,
    live_snapshot_at: datetime = _STARTED_AT,
    generated_at: datetime = _STARTED_AT,
    member_sha256: str | None = None,
    member_length: int | None = None,
) -> LivePlanGenerationReceiptV2:
    return LivePlanGenerationReceiptV2.build(
        generation_id=(
            f"generation-{generation_kind}-{_sha(sealed_plan_bytes)[:12]}-"
            f"{(parent_generation_receipt_sha256 or 'root')[:8]}"
        ),
        generation_kind=generation_kind,
        parent_generation_receipt_sha256=parent_generation_receipt_sha256,
        parent_capture_root_sha256=parent_capture_root_sha256,
        sealed_plan_bytes=sealed_plan_bytes,
        source_sha=attempt.source_sha,
        producing_head_sha=attempt.source_sha,
        workflow_path=".github/workflows/full-extraction.yml",
        workflow_content_sha256=_sha("workflow"),
        run_id=attempt.run_id,
        run_attempt=attempt.run_attempt,
        chain_id=attempt.chain_id,
        producer_job_id=202,
        producer_job_name_sha256=_sha("live-plan-producer"),
        runner_identity_sha256=_sha("runner"),
        matrix_lane_id=matrix_lane_id or attempt.lane_id,
        operation="full_live_capture",
        nonce_sha256=_sha("nonce"),
        artifact_id=303,
        artifact_name="live-plan-101-1-lane",
        artifact_digest_sha256=_sha("artifact-archive"),
        artifact_size=max(4_096, len(sealed_plan_bytes)),
        artifact_archive_url_sha256=_sha("artifact-url"),
        artifact_expires_at=_STARTED_AT + timedelta(days=1),
        member_path="live/plan.json",
        member_sha256=member_sha256 or _sha(sealed_plan_bytes),
        member_length=len(sealed_plan_bytes) if member_length is None else member_length,
        collector_receipt_sha256=_sha("collector"),
        external_receipt_sha256=external_receipt_sha256,
        live_snapshot_at=live_snapshot_at,
        generated_at=generated_at,
    )


def _admission(
    generation: LivePlanGenerationReceiptV2,
    attempt: RequestAttemptIdentityV2,
    *,
    ordinal: int = 0,
    issued_at: datetime = _STARTED_AT,
    authorized_at: datetime = _STARTED_AT,
    expires_at: datetime = _STARTED_AT + timedelta(hours=1),
) -> LivePlanCallAdmissionV2:
    return LivePlanCallAdmissionV2.build(
        generation=generation,
        attempt=attempt,
        plan_item_ordinal=ordinal,
        issued_at=issued_at,
        authorized_at=authorized_at,
        expires_at=expires_at,
        authorization_collector_receipt_sha256=_AUTHORIZATION_COLLECTOR,
        authorization_receipt_sha256=_AUTHORIZATION_RECEIPT,
    )


def _assert_external_authority_blocked(case: LiveCase) -> None:
    generation, admission, binding, bundle, _expected = case
    with pytest.raises(RawLivePlanAuthorityError, match="external authority source is unavailable"):
        validate_live_observation_plan_authority(
            generation,
            admission,
            binding,
            bundle,
        )


@pytest.fixture(scope="module")
def live_case() -> LiveCase:
    snapshot, logical_binding, committed_receipts = _case("live")
    provisional_authority = _live_plan_authority(
        snapshot,
        logical_binding,
        sealed_plan_bytes=b'{"kind":"provisional"}',
    )
    provisional_bundle = finalize_raw_request_capture(
        snapshot,
        logical_binding,
        committed_receipts,
        live_plan_authority=provisional_authority,
        expected_live_plan_authority_sha256=provisional_authority.authority_sha256,
    )
    attempt = provisional_bundle.observations[0].attempt
    plan_bytes = _plan_bytes(attempt, provisional_authority.route_ids)
    authority = _live_plan_authority(
        snapshot,
        logical_binding,
        sealed_plan_bytes=plan_bytes,
    )
    bundle = finalize_raw_request_capture(
        snapshot,
        logical_binding,
        committed_receipts,
        live_plan_authority=authority,
        expected_live_plan_authority_sha256=authority.authority_sha256,
    )
    generation = _generation(
        bundle.observations[0].attempt,
        sealed_plan_bytes=plan_bytes,
        live_snapshot_at=authority.live_snapshot_at,
        generated_at=bundle.observations[0].started_at,
    )
    admission = _admission(generation, bundle.observations[0].attempt)
    binding = LiveObservationPlanBindingV2.build(
        generation=generation,
        admission=admission,
        authority_bundle=bundle,
        observation_sha256=bundle.observations[0].attempt.observation_sha256,
    )
    return generation, admission, binding, bundle, authority


def test_exact_generation_binding_and_authority_round_trip(live_case: LiveCase) -> None:
    generation, admission, binding, bundle, expected = live_case

    _assert_external_authority_blocked(live_case)
    assert expected.authority_sha256 == binding.live_plan_authority_sha256
    assert generation.plan_item_count == 1
    assert admission.plan_item_sha256 == _sha(
        _canonical(_plan_item(bundle.observations[0].attempt, admission.route_ids))
    )
    assert binding.landing_sha256s == tuple(item.landing_sha256 for item in bundle.landings)
    assert binding.landing_receipt_roots == tuple(
        item.receipt_root_sha256 for item in bundle.landings
    )


def test_public_rows_schemas_and_restart_parsers_are_exact(live_case: LiveCase) -> None:
    generation, admission, binding, bundle, _authority = live_case
    generation_frame = pl.DataFrame(
        [generation.to_row()],
        schema_overrides={
            "parent_generation_receipt_sha256": pl.String,
            "parent_capture_root_sha256": pl.String,
        },
    )
    admission_frame = pl.DataFrame([admission.to_row()])
    binding_frame = pl.DataFrame([binding.to_row()])

    assert RawNbaApiLivePlanGenerationReceiptSchema.validate(generation_frame).height == 1
    assert RawNbaApiLivePlanCallAdmissionSchema.validate(admission_frame).height == 1
    assert RawNbaApiObservationLivePlanSchema.validate(binding_frame).height == 1
    generation_row = generation_frame.to_dicts()[0]
    admission_row = admission_frame.to_dicts()[0]
    binding_row = binding_frame.to_dicts()[0]
    assert LivePlanGenerationReceiptV2.from_row(generation_row) == generation
    assert LivePlanCallAdmissionV2.from_row(admission_row) == admission
    assert LiveObservationPlanBindingV2.from_row(binding_row) == binding
    with pytest.raises(RawLivePlanAuthorityError, match="external authority source is unavailable"):
        validate_live_plan_authority_tables(
            [generation_row],
            [admission_row],
            [binding_row],
            bundle,
        )

    with pytest.raises(pandera.errors.SchemaError):
        RawNbaApiObservationLivePlanSchema.validate(
            binding_frame.with_columns(pl.lit("extra").alias("unapproved_column"))
        )


@pytest.mark.parametrize(
    ("generation_kind", "parent_generation", "parent_capture"),
    [
        ("full_root", "a" * 64, None),
        ("full_root", None, "b" * 64),
        ("successor_wave_0", None, None),
        ("successor_wave_0", "a" * 64, "b" * 64),
        ("full_derived_game_fanout", None, "b" * 64),
        ("successor_wave_1", "a" * 64, None),
        ("successor_update", None, None),
    ],
)
def test_generation_parent_state_is_fail_closed(
    live_case: LiveCase,
    generation_kind: GenerationKind,
    parent_generation: str | None,
    parent_capture: str | None,
) -> None:
    generation, _admission_value, _binding, bundle, _authority = live_case
    with pytest.raises(RawLivePlanAuthorityError, match="parent"):
        _generation(
            bundle.observations[0].attempt,
            sealed_plan_bytes=generation.sealed_plan_bytes,
            generation_kind=generation_kind,
            parent_generation_receipt_sha256=parent_generation,
            parent_capture_root_sha256=parent_capture,
        )


@pytest.mark.parametrize(
    ("sealed_plan_bytes", "message"),
    [
        (b'{"items":[],"kind":"nbadb_live_execution_plan_v2","schema_version":2}', "absent"),
        (b'{"kind":"x","kind":"y","schema_version":2}', "duplicate"),
        (
            b'{"api_key":"plain-secret-value","items":[],"kind":"nbadb_live_execution_plan_v2","schema_version":2}',
            "root key set",
        ),
        (b'{"items":[],"kind":"wrong","schema_version":2}', "contract kind"),
        (
            b'{"items":[],"kind":"nbadb_live_execution_plan_v2","schema_version":1}',
            "exact integer 2",
        ),
        (b'[{"kind":"fixture","schema_version":2}]', "canonical JSON object"),
    ],
)
def test_sealed_plan_bytes_reject_ambiguous_or_untyped_content(
    live_case: LiveCase,
    sealed_plan_bytes: bytes,
    message: str,
) -> None:
    _generation_value, _admission_value, _binding, bundle, _authority = live_case
    with pytest.raises(RawLivePlanAuthorityError, match=message):
        _generation(bundle.observations[0].attempt, sealed_plan_bytes=sealed_plan_bytes)


def test_sealed_plan_rejects_secret_shaped_allowed_values(live_case: LiveCase) -> None:
    generation, _admission_value, _binding, bundle, _authority = live_case
    attempt = bundle.observations[0].attempt
    secret_route = f"ghp_{'A' * 20}"
    secret_plan = _plan_bytes(attempt, (secret_route,))
    with pytest.raises(RawLivePlanAuthorityError, match="secret-shaped"):
        _generation(attempt, sealed_plan_bytes=secret_plan)
    assert secret_route.encode("utf-8") not in generation.sealed_plan_bytes


def test_plan_rejects_semantic_duplicates_even_with_distinct_ordinals(
    live_case: LiveCase,
) -> None:
    generation, admission, _binding, bundle, _authority = live_case
    attempt = bundle.observations[0].attempt
    first = _plan_item(attempt, admission.route_ids)
    second = {**first, "plan_item_ordinal": 1}
    plan_bytes = _canonical({"items": [first, second], "kind": LIVE_PLAN_KIND, "schema_version": 2})
    with pytest.raises(RawLivePlanAuthorityError, match="semantic provider-call"):
        _generation(attempt, sealed_plan_bytes=plan_bytes)


def test_generation_kind_requires_an_exact_builtin_string(live_case: LiveCase) -> None:
    class ForeignGenerationKind(str):
        pass

    generation, _admission_value, _binding, bundle, _authority = live_case
    with pytest.raises(RawLivePlanAuthorityError, match="generation kind"):
        _generation(
            bundle.observations[0].attempt,
            sealed_plan_bytes=generation.sealed_plan_bytes,
            generation_kind=cast("Any", ForeignGenerationKind("full_root")),
        )


def test_artifact_member_must_equal_sealed_plan(live_case: LiveCase) -> None:
    generation, _admission_value, _binding, bundle, _authority = live_case
    attempt = bundle.observations[0].attempt
    with pytest.raises(RawLivePlanAuthorityError, match="artifact member"):
        _generation(
            attempt,
            sealed_plan_bytes=generation.sealed_plan_bytes,
            member_sha256="f" * 64,
        )
    with pytest.raises(RawLivePlanAuthorityError, match="artifact member"):
        _generation(
            attempt,
            sealed_plan_bytes=generation.sealed_plan_bytes,
            member_length=len(generation.sealed_plan_bytes) + 1,
        )


def test_generation_and_admission_require_exact_time_order(live_case: LiveCase) -> None:
    generation, _admission_value, _binding, bundle, _authority = live_case
    attempt = bundle.observations[0].attempt
    split = _SplitUtcDatetime(2099, 1, 1, tzinfo=UTC)

    with pytest.raises(RawLivePlanAuthorityError, match="exact aware UTC datetime"):
        _generation(attempt, sealed_plan_bytes=generation.sealed_plan_bytes, generated_at=split)
    with pytest.raises(RawLivePlanAuthorityError, match="validity window"):
        _admission(
            generation,
            attempt,
            issued_at=_STARTED_AT - timedelta(seconds=1),
            authorized_at=_STARTED_AT,
        )


def test_binding_rejects_post_call_authorization(live_case: LiveCase) -> None:
    generation, _admission_value, _binding, bundle, _authority = live_case
    attempt = bundle.observations[0].attempt
    late_generation = _generation(
        attempt,
        sealed_plan_bytes=generation.sealed_plan_bytes,
        generated_at=_STARTED_AT + timedelta(seconds=1),
    )
    late_admission = _admission(
        late_generation,
        attempt,
        issued_at=_STARTED_AT + timedelta(seconds=1),
        authorized_at=_STARTED_AT + timedelta(seconds=1),
    )
    with pytest.raises(RawLivePlanAuthorityError, match="authenticated pre-call"):
        LiveObservationPlanBindingV2.build(
            generation=late_generation,
            admission=late_admission,
            authority_bundle=bundle,
            observation_sha256=attempt.observation_sha256,
        )


def test_plan_item_membership_and_execution_identity_are_derived(live_case: LiveCase) -> None:
    generation, _admission_value, _binding, bundle, _authority = live_case
    attempt = bundle.observations[0].attempt
    with pytest.raises(RawLivePlanAuthorityError, match="missing plan item"):
        _admission(generation, attempt, ordinal=999)
    foreign_plan = _plan_bytes(attempt, ("foreign_route",))
    foreign_generation = _generation(attempt, sealed_plan_bytes=foreign_plan)
    foreign_admission = _admission(foreign_generation, attempt)
    with pytest.raises(RawLivePlanAuthorityError, match="landing denominator"):
        LiveObservationPlanBindingV2.build(
            generation=foreign_generation,
            admission=foreign_admission,
            authority_bundle=bundle,
            observation_sha256=attempt.observation_sha256,
        )
    crossed_generation = _generation(
        attempt,
        sealed_plan_bytes=generation.sealed_plan_bytes,
        matrix_lane_id="foreign-lane",
    )
    with pytest.raises(RawLivePlanAuthorityError, match="execution identity"):
        _admission(crossed_generation, attempt)


def test_table_closure_requires_a_disposition_for_every_plan_member(
    live_case: LiveCase,
) -> None:
    _generation_value, admission, _binding, bundle, _authority = live_case
    attempt = bundle.observations[0].attempt
    first = _plan_item(attempt, admission.route_ids)
    second = {
        **first,
        "plan_item_ordinal": 1,
        "semantic_request_sha256": _sha("second-semantic"),
        "logical_invocation_sha256": _sha("second-logical"),
        "provider_call_sha256": _sha("second-provider-call"),
        "scope_sha256": _sha("second-scope"),
        "safe_parameters_sha256": _sha("second-parameters"),
    }
    generation = _generation(
        attempt,
        sealed_plan_bytes=_canonical(
            {"items": [first, second], "kind": LIVE_PLAN_KIND, "schema_version": 2}
        ),
    )
    first_admission = _admission(generation, attempt)
    first_binding = LiveObservationPlanBindingV2.build(
        generation=generation,
        admission=first_admission,
        authority_bundle=bundle,
        observation_sha256=attempt.observation_sha256,
    )
    with pytest.raises(RawLivePlanAuthorityError, match="disposition denominator"):
        validate_live_plan_authority_tables(
            [generation],
            [first_admission],
            [first_binding],
            bundle,
        )


def test_restart_table_rows_and_public_bytes_are_aggregate_bounded(
    live_case: LiveCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation, admission, binding, bundle, _authority = live_case
    binding_row = binding.to_row()
    public_byte_bound = max(
        len(generation.sealed_plan_bytes),
        len(cast("str", admission.to_row()["route_ids_json"]).encode("utf-8")),
        sum(
            len(cast("str", binding_row[field_name]).encode("utf-8"))
            for field_name in (
                "route_ids_json",
                "landing_sha256s_json",
                "landing_receipt_roots_json",
            )
        ),
    )
    monkeypatch.setattr(raw_live_plan_authority, "_MAX_LIVE_PLAN_TABLE_ROWS", 1)
    monkeypatch.setattr(
        raw_live_plan_authority,
        "_MAX_LIVE_PLAN_TABLE_BYTES",
        public_byte_bound,
    )
    with pytest.raises(RawLivePlanAuthorityError, match="external authority source is unavailable"):
        validate_live_plan_authority_tables(
            [generation],
            [admission],
            [binding],
            bundle,
        )

    monkeypatch.setattr(raw_live_plan_authority, "_MAX_LIVE_PLAN_TABLE_ROWS", 0)
    with pytest.raises(RawLivePlanAuthorityError, match="row bound"):
        validate_live_plan_authority_tables(
            [generation],
            [admission],
            [binding],
            bundle,
        )

    monkeypatch.setattr(raw_live_plan_authority, "_MAX_LIVE_PLAN_TABLE_ROWS", 1)
    monkeypatch.setattr(
        raw_live_plan_authority,
        "_MAX_LIVE_PLAN_TABLE_BYTES",
        len(generation.sealed_plan_bytes) - 1,
    )
    with pytest.raises(RawLivePlanAuthorityError, match="public-byte bound"):
        validate_live_plan_authority_tables(
            [generation],
            [admission],
            [binding],
            bundle,
        )


def test_full_raw_bundle_landing_denominator_is_mandatory(live_case: LiveCase) -> None:
    generation, admission, _binding, bundle, _authority = live_case
    assert len(bundle.landings) > 1
    subset = bundle.model_copy(update={"landings": bundle.landings[:1]})
    with pytest.raises(RawLivePlanAuthorityError, match="invalid raw authority bundle"):
        LiveObservationPlanBindingV2.build(
            generation=generation,
            admission=admission,
            authority_bundle=cast("Any", subset),
            observation_sha256=admission.observation_sha256,
        )


def test_binding_restart_parser_rejects_coordinated_route_relabel(
    live_case: LiveCase,
) -> None:
    _generation_value, _admission_value, binding, _bundle, _authority = live_case
    row = binding.to_row()
    row["route_ids_json"] = '["foreign_route"]'
    row["route_ids_sha256"] = _sha(cast("str", row["route_ids_json"]))
    row["route_count"] = 1
    with pytest.raises(RawLivePlanAuthorityError, match="semantic reconstruction"):
        LiveObservationPlanBindingV2.from_row(row)


def test_collection_rejects_orphan_derived_generation(live_case: LiveCase) -> None:
    generation, admission, binding, bundle, _authority = live_case
    orphan = _generation(
        bundle.observations[0].attempt,
        sealed_plan_bytes=generation.sealed_plan_bytes,
        generation_kind="successor_update",
        parent_generation_receipt_sha256="f" * 64,
        parent_capture_root_sha256="d" * 64,
    )
    ordered = sorted((generation, orphan), key=lambda item: item.generation_receipt_sha256)
    with pytest.raises(RawLivePlanAuthorityError, match="orphan parent"):
        validate_live_plan_authority_tables(
            ordered,
            [admission],
            [binding],
            bundle,
        )


def test_independent_roots_and_strict_types_block_resealing(live_case: LiveCase) -> None:
    generation, admission, binding, bundle, _authority = live_case
    attempt = bundle.observations[0].attempt
    forged_generation = _generation(
        attempt,
        sealed_plan_bytes=generation.sealed_plan_bytes,
        external_receipt_sha256="f" * 64,
    )
    forged_admission = _admission(forged_generation, attempt)
    forged_binding = LiveObservationPlanBindingV2.build(
        generation=forged_generation,
        admission=forged_admission,
        authority_bundle=bundle,
        observation_sha256=attempt.observation_sha256,
    )
    with pytest.raises(RawLivePlanAuthorityError, match="external authority source is unavailable"):
        validate_live_observation_plan_authority(
            forged_generation,
            forged_admission,
            forged_binding,
            bundle,
        )

    forged_parent_capture = _generation(
        attempt,
        sealed_plan_bytes=generation.sealed_plan_bytes,
        generation_kind="successor_update",
        parent_generation_receipt_sha256=generation.generation_receipt_sha256,
        parent_capture_root_sha256="f" * 64,
    )
    forged_parent_admission = _admission(forged_parent_capture, attempt)
    forged_parent_binding = LiveObservationPlanBindingV2.build(
        generation=forged_parent_capture,
        admission=forged_parent_admission,
        authority_bundle=bundle,
        observation_sha256=attempt.observation_sha256,
    )
    with pytest.raises(RawLivePlanAuthorityError, match="external authority source is unavailable"):
        validate_live_observation_plan_authority(
            forged_parent_capture,
            forged_parent_admission,
            forged_parent_binding,
            bundle,
        )

    with pytest.raises(RawLivePlanAuthorityError, match="exact contract type"):
        validate_live_observation_plan_authority(
            cast("Any", object()),
            admission,
            binding,
            bundle,
        )
