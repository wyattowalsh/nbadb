from __future__ import annotations

from dataclasses import replace

import pytest

from nbadb.orchestrate.checkpoint_contract import (
    CheckpointArtifactReceipt,
    CheckpointTransaction,
    CheckpointW2AuthorityIdentity,
)
from nbadb.orchestrate.terminal_catchup import (
    TERMINAL_CATCHUP_SCHEMA_VERSION,
    CatchupComponentInventoryV1,
    CoalescedTailDemandV1,
    FreshBaselineAuthorityV1,
    FreshnessStatus,
    GenerationArtifactReceiptV1,
    GenerationKind,
    GenerationState,
    ObservationCallV1,
    ObservationWindowV1,
    TailGenerationIdentityV1,
    TailGenerationTransactionV1,
    TailTriggerDemandV1,
    TerminalCatchupContractError,
    TerminalCatchupIdentityV1,
    TerminalCatchupTransactionV1,
    TerminalCatchupTransitionError,
    TriggerKind,
    canonical_json_bytes,
)
from nbadb.orchestrate.w2_database_assurance import W2DatabaseAuthorityReceiptV1
from nbadb.orchestrate.w2_operation_store import RAW_NBA_API_W2_OPERATION_TABLE
from nbadb.orchestrate.w2_publication_inventory import (
    w2_public_value_authority_publication_tables,
)

_SOURCE_SHA = "a" * 40


def _sha(character: str) -> str:
    return character * 64


def _w2_authority(
    *,
    call_count: int,
    expected_call_inventory_sha256: str,
    salt: str,
) -> CheckpointW2AuthorityIdentity:
    relation_counts = tuple(
        sorted(
            (
                entry.table_name,
                call_count if entry.table_name == RAW_NBA_API_W2_OPERATION_TABLE else 0,
            )
            for entry in w2_public_value_authority_publication_tables()
        )
    )
    receipt = W2DatabaseAuthorityReceiptV1.build(
        w2_required_logical_call_count=call_count,
        w2_source_call_admission_inventory_sha256=_sha(salt),
        raw_authority_v2_bundle_count=call_count,
        raw_authority_v2_bundle_inventory_sha256=_sha(salt),
        raw_authority_v2_persistence_receipt_inventory_sha256=_sha(salt),
        w2_publication_receipt_count=call_count,
        w2_publication_receipt_inventory_sha256=_sha(salt),
        w2_exact_six_schema_inventory_sha256=_sha(salt),
        w2_relation_row_counts=relation_counts,
        w2_relation_row_count=sum(row_count for _table_name, row_count in relation_counts),
        w2_relation_inventory_sha256=_sha(salt),
    )
    return CheckpointW2AuthorityIdentity(
        database_authority=receipt,
        database_authority_sha256=receipt.receipt_sha256,
        expected_call_count=call_count,
        expected_call_inventory_sha256=expected_call_inventory_sha256,
        database_authority_closed=True,
    )


def _committed_checkpoint(
    *,
    w2_authority: CheckpointW2AuthorityIdentity | None = None,
) -> CheckpointTransaction:
    w2_authority = w2_authority or _w2_authority(
        call_count=0,
        expected_call_inventory_sha256=_sha("7"),
        salt="8",
    )
    candidate = CheckpointTransaction.candidate(
        chain_id="fresh-full-model-chain",
        source_sha=_SOURCE_SHA,
        generation=7,
        artifact_name="full-extraction-checkpoint-fresh-full-model-chain-7",
        lane_contracts=(),
        coverage_fingerprint=_sha("6"),
    )
    built = candidate.mark_built(
        database_sha256=_sha("9"),
        report_sha256=_sha("a"),
        w2_authority=w2_authority,
    )
    receipt = CheckpointArtifactReceipt(
        artifact_id=7001,
        artifact_run_id=1001,
        artifact_run_attempt=1,
        artifact_name=candidate.artifact_name,
        artifact_digest="sha256:" + _sha("8"),
        artifact_size_bytes=4096,
        database_sha256=built.build.database_sha256,
        report_sha256=built.build.report_sha256,
        chain_id=candidate.identity.chain_id,
        source_sha=candidate.identity.source_sha,
        generation=candidate.identity.generation,
        coverage_fingerprint=candidate.identity.coverage.coverage_fingerprint,
        lane_inventory_sha256=candidate.identity.coverage.lane_inventory_sha256,
        w2_authority_identity_sha256=w2_authority.identity_sha256,
    )
    return built.mark_uploaded_verified(receipt).commit()


def _call(
    call_id: str,
    *,
    request: str,
    body: str | None,
    bodyless: str | None,
    field: str,
    started: str,
    ended: str,
) -> ObservationCallV1:
    return ObservationCallV1(
        call_id=call_id,
        request_identity_sha256=_sha(request),
        parser_input_body_sha256=_sha(body) if body is not None else None,
        bodyless_receipt_sha256=_sha(bodyless) if bodyless is not None else None,
        field_temporal_receipt_sha256=_sha(field),
        observation_started_at=started,
        observation_ended_at=ended,
    )


def _catchup_window() -> ObservationWindowV1:
    return ObservationWindowV1.sealed(
        calls=(
            _call(
                "baseline-to-cutoff",
                request="1",
                body="2",
                bodyless=None,
                field="3",
                started="2026-08-26T12:00:00Z",
                ended="2026-08-26T12:01:00Z",
            ),
            _call(
                "frozen-live",
                request="4",
                body=None,
                bodyless="5",
                field="6",
                started="2026-08-26T12:01:00Z",
                ended="2026-08-26T12:02:00Z",
            ),
        ),
        seal_at="2026-08-26T12:03:00Z",
    )


def _baseline(
    *,
    checkpoint: CheckpointTransaction | None = None,
    **changes: object,
) -> FreshBaselineAuthorityV1:
    baseline = FreshBaselineAuthorityV1.from_committed_checkpoint(
        repository="w4w/nbadb",
        checkpoint=checkpoint or _committed_checkpoint(),
        run_attempt=1,
        request_universe_generation_sha256=_sha("b"),
    )
    return replace(baseline, **changes)


def _components(**changes: object) -> CatchupComponentInventoryV1:
    components = CatchupComponentInventoryV1(
        baseline_to_cutoff_sha256=_sha("c"),
        overlap_refresh_sha256=_sha("d"),
        hole_repair_sha256=_sha("e"),
        live_snapshot_sha256=_sha("f"),
    )
    return replace(components, **changes)


def _catchup_identity(
    *,
    window: ObservationWindowV1 | None = None,
    baseline: FreshBaselineAuthorityV1 | None = None,
    components: CatchupComponentInventoryV1 | None = None,
    source_sha: str = _SOURCE_SHA,
    w2_expected_call_count: int | None = None,
    w2_expected_call_inventory_sha256: str | None = None,
) -> TerminalCatchupIdentityV1:
    window = window or _catchup_window()
    baseline = baseline or _baseline()
    components = components or _components()
    return TerminalCatchupIdentityV1(
        generation_id="terminal-catchup-1",
        baseline_authority=baseline,
        source_sha=source_sha,
        semantic_diff_sha256=_sha("0"),
        request_universe_generation_sha256=baseline.request_universe_generation_sha256,
        public_observation_inventory_sha256=window.call_inventory_sha256,
        parser_body_inventory_sha256=window.parser_body_inventory_sha256,
        bodyless_inventory_sha256=window.bodyless_inventory_sha256,
        field_temporal_authority_sha256=window.field_temporal_inventory_sha256,
        model_contract_sha256=_sha("1"),
        event_cutoff="2026-08-26T11:59:59Z",
        overlap_scope_sha256=_sha("2"),
        hole_repair_inventory_sha256=components.hole_repair_sha256,
        live_snapshot_sha256=components.live_snapshot_sha256,
        observation_window=window,
        components=components,
        canonical_request_inventory_sha256=window.canonical_request_inventory_sha256,
        w2_expected_call_count=(
            baseline.checkpoint_w2_authority.expected_call_count + len(window.calls)
            if w2_expected_call_count is None
            else w2_expected_call_count
        ),
        w2_expected_call_inventory_sha256=(
            _sha("c")
            if w2_expected_call_inventory_sha256 is None
            else w2_expected_call_inventory_sha256
        ),
    )


def _receipt(
    transaction: TerminalCatchupTransactionV1 | TailGenerationTransactionV1,
    **changes: object,
) -> GenerationArtifactReceiptV1:
    assert transaction.build is not None
    receipt = GenerationArtifactReceiptV1(
        artifact_id=9001,
        artifact_run_id=1001,
        artifact_name=transaction.artifact_name,
        artifact_digest="sha256:" + _sha("3"),
        artifact_size_bytes=4096,
        generation_kind=transaction.kind,
        generation_id=transaction.identity.generation_id,
        source_sha=transaction.identity.source_sha,
        identity_sha256=transaction.identity.identity_sha256,
        parent_authority_sha256=transaction.identity.parent_authority_sha256,
        database_sha256=transaction.build.database_sha256,
        report_sha256=transaction.build.report_sha256,
        component_inventory_sha256=transaction.build.component_inventory_sha256,
        w2_authority=transaction.build.w2_authority,
        w2_authority_identity_sha256=transaction.build.w2_authority.identity_sha256,
    )
    return replace(receipt, **changes)


def _committed_catchup() -> TerminalCatchupTransactionV1:
    identity = _catchup_identity()
    candidate = TerminalCatchupTransactionV1.candidate(
        identity=identity,
        artifact_name="terminal-catchup-fresh-full-model-chain-1",
    )
    built = candidate.mark_built(
        database_sha256=_sha("4"),
        report_sha256=_sha("5"),
        w2_authority=_w2_authority(
            call_count=identity.w2_expected_call_count,
            expected_call_inventory_sha256=identity.w2_expected_call_inventory_sha256,
            salt="d",
        ),
    )
    uploaded = built.mark_uploaded_verified(_receipt(built))
    return uploaded.commit()


def _tail_window() -> ObservationWindowV1:
    return ObservationWindowV1.sealed(
        calls=(
            _call(
                "next-day",
                request="6",
                body="7",
                bodyless=None,
                field="8",
                started="2026-08-29T00:00:00Z",
                ended="2026-08-29T00:01:00Z",
            ),
        ),
        seal_at="2026-08-29T01:00:00Z",
    )


def _tail_identity(
    *,
    parent_transaction: TerminalCatchupTransactionV1 | TailGenerationTransactionV1 | None = None,
    window: ObservationWindowV1 | None = None,
    source_sha: str | None = None,
    semantic_diff_sha256: str | None = None,
    event_cutoff: str = "2026-08-29T00:30:00Z",
    w2_expected_call_count: int | None = None,
    w2_expected_call_inventory_sha256: str | None = None,
) -> TailGenerationIdentityV1:
    parent_transaction = parent_transaction or _committed_catchup()
    parent = parent_transaction.committed_authority()
    window = window or _tail_window()
    return TailGenerationIdentityV1(
        generation_id="tail-1",
        parent=parent,
        source_sha=source_sha or parent.source_sha,
        semantic_diff_sha256=semantic_diff_sha256 or parent.semantic_diff_sha256,
        request_universe_generation_sha256=parent.request_universe_generation_sha256,
        event_cutoff=event_cutoff,
        overlap_scope_sha256=_sha("9"),
        parser_body_inventory_sha256=window.parser_body_inventory_sha256,
        bodyless_inventory_sha256=window.bodyless_inventory_sha256,
        field_temporal_authority_sha256=window.field_temporal_inventory_sha256,
        canonical_request_inventory_sha256=window.canonical_request_inventory_sha256,
        observation_window=window,
        w2_expected_call_count=(
            parent.w2_authority.expected_call_count + len(window.calls)
            if w2_expected_call_count is None
            else w2_expected_call_count
        ),
        w2_expected_call_inventory_sha256=(
            _sha("e")
            if w2_expected_call_inventory_sha256 is None
            else w2_expected_call_inventory_sha256
        ),
    )


def _committed_tail(
    *,
    parent_transaction: TerminalCatchupTransactionV1 | TailGenerationTransactionV1 | None = None,
    event_cutoff: str = "2026-08-29T00:30:00Z",
) -> TailGenerationTransactionV1:
    candidate = TailGenerationTransactionV1.candidate(
        identity=_tail_identity(
            parent_transaction=parent_transaction,
            event_cutoff=event_cutoff,
        ),
        artifact_name="tail-terminal-catchup-1-1",
    )
    identity = candidate.identity
    built = candidate.mark_built(
        database_sha256=_sha("a"),
        report_sha256=_sha("b"),
        w2_authority=_w2_authority(
            call_count=identity.w2_expected_call_count,
            expected_call_inventory_sha256=identity.w2_expected_call_inventory_sha256,
            salt="f",
        ),
    )
    return built.mark_uploaded_verified(_receipt(built, artifact_id=9002)).commit()


def test_terminal_catchup_four_state_transaction_and_round_trip() -> None:
    identity = _catchup_identity()
    candidate = TerminalCatchupTransactionV1.candidate(
        identity=identity,
        artifact_name="terminal-catchup-fresh-full-model-chain-1",
    )
    assert candidate.state is GenerationState.CANDIDATE
    assert candidate.kind is GenerationKind.TERMINAL_CATCHUP

    w2_authority = _w2_authority(
        call_count=identity.w2_expected_call_count,
        expected_call_inventory_sha256=identity.w2_expected_call_inventory_sha256,
        salt="d",
    )
    built = candidate.mark_built(
        database_sha256=_sha("4"),
        report_sha256=_sha("5"),
        w2_authority=w2_authority,
    )
    uploaded = built.mark_uploaded_verified(_receipt(built))
    committed = uploaded.commit()

    assert built.state is GenerationState.BUILT
    assert uploaded.state is GenerationState.UPLOADED_VERIFIED
    assert committed.state is GenerationState.COMMITTED
    assert candidate.to_dict()["schema_version"] == TERMINAL_CATCHUP_SCHEMA_VERSION
    assert (
        identity.baseline_authority.checkpoint_w2_authority
        == identity.baseline_authority.checkpoint_transaction.build.w2_authority
    )
    assert built.build.w2_authority == w2_authority
    assert uploaded.receipt.w2_authority == w2_authority
    assert uploaded.receipt.w2_authority_identity_sha256 == w2_authority.identity_sha256
    assert committed.committed_receipt.artifact_id == 9001
    assert committed.committed_authority().w2_authority == w2_authority
    assert TerminalCatchupTransactionV1.from_dict(committed.to_dict()) == committed
    assert TerminalCatchupTransactionV1.from_bytes(committed.to_bytes()) == committed
    assert committed.to_bytes() == canonical_json_bytes(committed.to_dict())
    assert b"/Users/" not in committed.to_bytes()


def test_observation_window_binds_bodies_fields_timing_and_seal() -> None:
    window = _catchup_window()

    assert window.minimum_start == "2026-08-26T12:00:00Z"
    assert window.maximum_accepted_end == "2026-08-26T12:02:00Z"
    assert len(window.call_inventory_sha256) == 64
    assert ObservationWindowV1.from_dict(window.to_dict()) == window

    post_seal = replace(
        window.calls[1],
        observation_ended_at="2026-08-26T12:04:00Z",
    )
    with pytest.raises(TerminalCatchupContractError, match="post-seal"):
        ObservationWindowV1.sealed(
            calls=(window.calls[0], post_seal),
            seal_at="2026-08-26T12:03:00Z",
        )
    with pytest.raises(TerminalCatchupContractError, match="exactly one"):
        replace(window.calls[0], bodyless_receipt_sha256=_sha("a"))
    with pytest.raises(TerminalCatchupContractError, match="start"):
        replace(
            window.calls[0],
            observation_started_at="2026-08-26T12:02:00Z",
        )


def test_fresh_baseline_forbids_later_attempt_and_prior_state_reuse() -> None:
    with pytest.raises(TerminalCatchupContractError, match="attempt one"):
        _baseline(run_attempt=2)
    with pytest.raises(TerminalCatchupContractError, match="fresh empty"):
        _baseline(fresh_empty_candidate=False)
    with pytest.raises(TerminalCatchupContractError, match="prior checkpoint"):
        _baseline(prior_state_reused=True)
    with pytest.raises(TerminalCatchupContractError, match="committed checkpoint"):
        _baseline(checkpoint_state=GenerationState.BUILT)


def test_catchup_requires_all_four_exact_component_and_authority_identities() -> None:
    identity = _catchup_identity()
    assert identity.component_inventory_sha256 == identity.components.inventory_sha256

    with pytest.raises(TerminalCatchupContractError, match="hole_repair"):
        replace(identity, hole_repair_inventory_sha256=_sha("9"))
    with pytest.raises(TerminalCatchupContractError, match="live_snapshot"):
        replace(identity, live_snapshot_sha256=_sha("9"))
    with pytest.raises(TerminalCatchupContractError, match="parser_body"):
        replace(identity, parser_body_inventory_sha256=_sha("9"))
    with pytest.raises(TerminalCatchupContractError, match="source drifts"):
        _catchup_identity(source_sha="b" * 40)


def test_transaction_transitions_and_receipt_mutations_fail_closed() -> None:
    candidate = TerminalCatchupTransactionV1.candidate(
        identity=_catchup_identity(),
        artifact_name="terminal-catchup-fresh-full-model-chain-1",
    )
    candidate_w2 = _w2_authority(
        call_count=candidate.identity.w2_expected_call_count,
        expected_call_inventory_sha256=(candidate.identity.w2_expected_call_inventory_sha256),
        salt="d",
    )
    with pytest.raises(TerminalCatchupTransitionError, match="expected built"):
        candidate.mark_uploaded_verified(
            GenerationArtifactReceiptV1(
                artifact_id=1,
                artifact_run_id=1,
                artifact_name=candidate.artifact_name,
                artifact_digest="sha256:" + _sha("1"),
                artifact_size_bytes=1,
                generation_kind=candidate.kind,
                generation_id=candidate.identity.generation_id,
                source_sha=candidate.identity.source_sha,
                identity_sha256=candidate.identity.identity_sha256,
                parent_authority_sha256=candidate.identity.parent_authority_sha256,
                database_sha256=_sha("2"),
                report_sha256=_sha("3"),
                component_inventory_sha256=candidate.identity.component_inventory_sha256,
                w2_authority=candidate_w2,
                w2_authority_identity_sha256=candidate_w2.identity_sha256,
            )
        )
    with pytest.raises(TerminalCatchupTransitionError, match="expected uploaded_verified"):
        candidate.commit()

    built = candidate.mark_built(
        database_sha256=_sha("4"),
        report_sha256=_sha("5"),
        w2_authority=candidate_w2,
    )
    with pytest.raises(TerminalCatchupContractError, match="identity_sha256"):
        built.mark_uploaded_verified(_receipt(built, identity_sha256=_sha("f")))
    with pytest.raises(TerminalCatchupContractError, match="artifact_name"):
        built.mark_uploaded_verified(_receipt(built, artifact_name="other"))


def test_transaction_replay_rejects_identity_mutation_extra_fields_and_noncanonical_bytes() -> None:
    committed = _committed_catchup()
    payload = committed.to_dict()
    identity = payload["identity"]
    assert isinstance(identity, dict)
    identity["model_contract_sha256"] = _sha("f")
    with pytest.raises(TerminalCatchupContractError, match="identity digest"):
        TerminalCatchupTransactionV1.from_dict(payload)

    payload = committed.to_dict()
    payload["unexpected"] = True
    with pytest.raises(TerminalCatchupContractError, match="unexpected"):
        TerminalCatchupTransactionV1.from_dict(payload)

    with pytest.raises(TerminalCatchupContractError, match="canonically"):
        TerminalCatchupTransactionV1.from_bytes(committed.to_bytes() + b"\n")
    with pytest.raises(TerminalCatchupContractError, match="duplicate"):
        TerminalCatchupTransactionV1.from_bytes(b'{"schema_version":2,"schema_version":2}')


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_checkpoint_w2",
        "partial_successor_w2",
        "foreign_checkpoint_w2",
        "foreign_receipt_w2",
        "legacy_schema",
        "downgraded_successor_w2",
        "not_closed",
    ],
)
def test_replay_rejects_missing_partial_foreign_legacy_and_downgraded_w2(
    mutation: str,
) -> None:
    committed = _committed_catchup()
    payload = committed.to_dict()
    identity = payload["identity"]
    build = payload["build"]
    receipt = payload["receipt"]
    assert isinstance(identity, dict)
    assert isinstance(build, dict)
    assert isinstance(receipt, dict)
    baseline = identity["baseline_authority"]
    build_w2 = build["w2_authority"]
    assert isinstance(baseline, dict)
    assert isinstance(build_w2, dict)

    if mutation == "missing_checkpoint_w2":
        baseline.pop("checkpoint_w2_authority")
    elif mutation == "partial_successor_w2":
        build_w2.pop("w2_expected_call_inventory_sha256")
    elif mutation == "foreign_checkpoint_w2":
        checkpoint_w2 = committed.identity.baseline_authority.checkpoint_w2_authority
        foreign = _w2_authority(
            call_count=checkpoint_w2.expected_call_count,
            expected_call_inventory_sha256=checkpoint_w2.expected_call_inventory_sha256,
            salt="1",
        )
        baseline["checkpoint_w2_authority"] = foreign.to_dict()
        baseline["checkpoint_w2_authority_identity_sha256"] = foreign.identity_sha256
    elif mutation == "foreign_receipt_w2":
        foreign = _w2_authority(
            call_count=committed.identity.w2_expected_call_count,
            expected_call_inventory_sha256=(committed.identity.w2_expected_call_inventory_sha256),
            salt="1",
        )
        receipt["w2_authority"] = foreign.to_dict()
        receipt["w2_authority_identity_sha256"] = foreign.identity_sha256
    elif mutation == "legacy_schema":
        payload["schema_version"] = 1
    elif mutation == "downgraded_successor_w2":
        downgraded = _w2_authority(
            call_count=committed.identity.w2_expected_call_count - 1,
            expected_call_inventory_sha256=(committed.identity.w2_expected_call_inventory_sha256),
            salt="1",
        )
        build["w2_authority"] = downgraded.to_dict()
    else:
        build_w2["w2_database_authority_closed"] = False

    with pytest.raises(
        TerminalCatchupContractError,
        match="W2|w2|schema|fields|expected-call|checkpoint",
    ):
        TerminalCatchupTransactionV1.from_dict(payload)


def test_committed_tail_is_parent_bound_immutable_and_round_trips() -> None:
    catchup = _committed_catchup()
    parent_before = catchup.to_bytes()
    tail = _committed_tail(parent_transaction=catchup)

    assert tail.kind is GenerationKind.TAIL
    assert tail.state is GenerationState.COMMITTED
    assert isinstance(tail.identity, TailGenerationIdentityV1)
    assert tail.identity.parent.authority_sha256 == catchup.committed_authority().authority_sha256
    assert tail.identity.parent.w2_authority == catchup.committed_authority().w2_authority
    assert tail.build is not None
    assert tail.receipt is not None
    assert tail.build.w2_authority == tail.receipt.w2_authority
    assert tail.receipt.w2_authority_identity_sha256 == tail.build.w2_authority.identity_sha256
    assert catchup.to_bytes() == parent_before
    assert TailGenerationTransactionV1.from_dict(tail.to_dict()) == tail
    assert TailGenerationTransactionV1.from_bytes(tail.to_bytes()) == tail


def test_tail_rejects_parent_source_semantic_and_request_authority_drift() -> None:
    with pytest.raises(TerminalCatchupContractError, match="fresh baseline.*source_sha"):
        _tail_identity(source_sha="b" * 40)
    with pytest.raises(TerminalCatchupContractError, match="fresh baseline.*semantic"):
        _tail_identity(semantic_diff_sha256=_sha("f"))

    identity = _tail_identity()
    with pytest.raises(TerminalCatchupContractError, match="fresh baseline.*request"):
        replace(identity, request_universe_generation_sha256=_sha("f"))
    with pytest.raises(TerminalCatchupContractError, match="cannot downgrade"):
        _tail_identity(w2_expected_call_count=identity.parent.w2_authority.expected_call_count - 1)


def test_post_seal_work_cannot_be_relabelled_into_parent_or_preseal_tail() -> None:
    catchup = _committed_catchup()
    parent = catchup.committed_authority()
    preseal_window = ObservationWindowV1.sealed(
        calls=(
            _call(
                "too-old",
                request="1",
                body="2",
                bodyless=None,
                field="3",
                started="2026-08-26T12:02:00Z",
                ended=parent.observation_seal_at,
            ),
        ),
        seal_at="2026-08-26T12:04:00Z",
    )
    with pytest.raises(TerminalCatchupContractError, match="after.*parent seal"):
        _tail_identity(
            parent_transaction=catchup,
            window=preseal_window,
            event_cutoff="2026-08-26T12:03:30Z",
        )

    with pytest.raises(TerminalCatchupContractError, match="advance"):
        _tail_identity(parent_transaction=catchup, event_cutoff=parent.event_cutoff)


def _demand(
    trigger_id: str,
    trigger_kind: TriggerKind,
    desired_cutoff: str,
    *,
    parent_sha256: str,
) -> TailTriggerDemandV1:
    return TailTriggerDemandV1(
        trigger_id=trigger_id,
        trigger_kind=trigger_kind,
        parent_authority_sha256=parent_sha256,
        desired_cutoff=desired_cutoff,
    )


def test_trigger_demand_coalesces_monotonically_without_duplicate_generation() -> None:
    catchup = _committed_catchup()
    parent = catchup.committed_authority()
    daily = _demand(
        "daily-1",
        TriggerKind.DAILY,
        "2026-08-28T00:00:00Z",
        parent_sha256=parent.authority_sha256,
    )
    opportunistic = _demand(
        "opportunistic-1",
        TriggerKind.OPPORTUNISTIC,
        "2026-08-29T00:00:00Z",
        parent_sha256=parent.authority_sha256,
    )
    coalesced = CoalescedTailDemandV1.create(
        parent=parent,
        generation_id="tail-1",
        demand=daily,
    ).add(opportunistic)

    assert coalesced.generation_id == "tail-1"
    assert coalesced.desired_cutoff == "2026-08-29T00:00:00Z"
    assert len(coalesced.demands) == 2
    assert CoalescedTailDemandV1.from_dict(coalesced.to_dict()) == coalesced
    assert CoalescedTailDemandV1.from_bytes(coalesced.to_bytes()) == coalesced

    with pytest.raises(TerminalCatchupContractError, match="trigger IDs"):
        coalesced.add(daily)
    with pytest.raises(TerminalCatchupContractError, match="foreign parent"):
        coalesced.add(
            replace(opportunistic, trigger_id="foreign", parent_authority_sha256=_sha("f"))
        )


def test_coalesced_outcomes_distinguish_fresh_not_fresh_and_capacity_blocked() -> None:
    catchup = _committed_catchup()
    parent = catchup.committed_authority()
    demand = _demand(
        "daily-1",
        TriggerKind.DAILY,
        "2026-08-29T00:00:00Z",
        parent_sha256=parent.authority_sha256,
    )
    coalesced = CoalescedTailDemandV1.create(
        parent=parent,
        generation_id="tail-1",
        demand=demand,
    )

    fresh = coalesced.finish(
        status=FreshnessStatus.FRESH,
        admission_sha256=_sha("1"),
        provider_observation_sha256=_sha("2"),
        committed_tail=_committed_tail(parent_transaction=catchup),
    )
    not_fresh = coalesced.finish(
        status=FreshnessStatus.NOT_FRESH,
        admission_sha256=_sha("1"),
        provider_observation_sha256=_sha("3"),
        committed_tail=None,
    )
    blocked = coalesced.finish(
        status=FreshnessStatus.CAPACITY_BLOCKED,
        admission_sha256=_sha("4"),
        provider_observation_sha256=None,
        committed_tail=None,
    )

    assert fresh[0].status is FreshnessStatus.FRESH
    assert fresh[0].committed_tail_transaction_sha256 is not None
    assert not_fresh[0].status is FreshnessStatus.NOT_FRESH
    assert not_fresh[0].committed_tail_transaction_sha256 is None
    assert blocked[0].status is FreshnessStatus.CAPACITY_BLOCKED
    assert blocked[0].provider_observation_sha256 is None


def test_freshness_outcomes_cannot_fabricate_work_or_relabel_foreign_tail() -> None:
    catchup = _committed_catchup()
    parent = catchup.committed_authority()
    coalesced = CoalescedTailDemandV1.create(
        parent=parent,
        generation_id="tail-1",
        demand=_demand(
            "daily-1",
            TriggerKind.DAILY,
            "2026-08-29T00:00:00Z",
            parent_sha256=parent.authority_sha256,
        ),
    )
    with pytest.raises(TerminalCatchupContractError, match="requires one committed tail"):
        coalesced.finish(
            status=FreshnessStatus.FRESH,
            admission_sha256=_sha("1"),
            provider_observation_sha256=_sha("2"),
            committed_tail=None,
        )
    with pytest.raises(TerminalCatchupContractError, match="requires provider"):
        coalesced.finish(
            status=FreshnessStatus.NOT_FRESH,
            admission_sha256=_sha("1"),
            provider_observation_sha256=None,
            committed_tail=None,
        )
    with pytest.raises(TerminalCatchupContractError, match="cannot claim provider"):
        coalesced.finish(
            status=FreshnessStatus.CAPACITY_BLOCKED,
            admission_sha256=_sha("1"),
            provider_observation_sha256=_sha("2"),
            committed_tail=None,
        )

    other_candidate = TerminalCatchupTransactionV1.candidate(
        identity=replace(_catchup_identity(), generation_id="terminal-catchup-other"),
        artifact_name="terminal-catchup-other",
    )
    other_built = other_candidate.mark_built(
        database_sha256=_sha("d"),
        report_sha256=_sha("e"),
        w2_authority=_w2_authority(
            call_count=other_candidate.identity.w2_expected_call_count,
            expected_call_inventory_sha256=(
                other_candidate.identity.w2_expected_call_inventory_sha256
            ),
            salt="d",
        ),
    )
    other_parent = other_built.mark_uploaded_verified(
        _receipt(other_built, artifact_id=9100)
    ).commit()
    foreign_tail = _committed_tail(parent_transaction=other_parent)
    with pytest.raises(TerminalCatchupContractError, match="foreign parent"):
        coalesced.finish(
            status=FreshnessStatus.FRESH,
            admission_sha256=_sha("1"),
            provider_observation_sha256=_sha("2"),
            committed_tail=foreign_tail,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"run_id": True},
        {"checkpoint_artifact_id": True},
        {"fresh_empty_candidate": 1},
        {"prior_state_reused": 0},
    ],
)
def test_baseline_rejects_boolean_integer_aliases(
    changes: dict[str, object],
) -> None:
    with pytest.raises(TerminalCatchupContractError):
        _baseline(**changes)
