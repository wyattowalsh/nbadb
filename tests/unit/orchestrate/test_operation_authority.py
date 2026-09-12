from __future__ import annotations

from dataclasses import replace

import pytest

from nbadb.orchestrate.operation_authority import (
    ACTION_DISPATCH_EVENT,
    DIRECT_PARALLELISM_LIMIT,
    OPERATION_AUTHORITY_SCHEMA_VERSION,
    VPN_PARALLELISM_DEFAULT,
    VPN_PARALLELISM_LIMIT,
    ActionsRuntimeView,
    ExactArtifactMemberV1,
    NetworkMode,
    OperationAuthorityError,
    OperationAuthorityV1,
    OperationKind,
)

_REPOSITORY = "wyattowalsh/nbadb"
_SOURCE_SHA = "a" * 40
_WORKFLOW_SHA = "b" * 40
_CONTENT_SHA = "c" * 64
_TRUSTED_REF = "refs/heads/main"
_RUN_ID = 2024

_ALL_OPERATIONS = tuple(OperationKind)


def _member(**overrides: object) -> ExactArtifactMemberV1:
    values: dict[str, object] = {
        "repository": _REPOSITORY,
        "run_id": 101,
        "run_attempt": 2,
        "artifact_id": 9001,
        "artifact_name": "chain-manifest-run101",
        "artifact_digest": "sha256:" + "d" * 64,
        "artifact_size_bytes": 128,
        "member_path": "manifests/next-manifest.json",
        "member_sha256": "e" * 64,
        "member_size_bytes": 64,
    }
    values.update(overrides)
    return ExactArtifactMemberV1(**values)


def _authority(
    operation: OperationKind,
    /,
    **overrides: object,
) -> OperationAuthorityV1:
    values: dict[str, object] = {
        "repository": _REPOSITORY,
        "workflow_path": ".github/workflows/full-extraction.yml",
        "workflow_content_sha256": _CONTENT_SHA,
        "workflow_commit_sha": _WORKFLOW_SHA,
        "source_sha": _SOURCE_SHA,
        "trusted_ref": _TRUSTED_REF,
        "run_id": _RUN_ID,
        "run_attempt": 1,
        "event": ACTION_DISPATCH_EVENT,
        "actor": "wyattowalsh",
        "chain_id": "chain-0001",
        "iteration": 1,
        "operation": operation,
        "requested_network_mode": NetworkMode.VPN,
        "requested_vpn_parallelism": VPN_PARALLELISM_DEFAULT,
        "requested_direct_parallelism": 0,
        "max_iterations": 1,
        "retry_pipeline_failures": False,
        "allow_re_extraction": False,
        "manifest_lane_count": 1,
    }
    if operation is OperationKind.TARGETED_SMOKE:
        values["requested_vpn_parallelism"] = 1
    if operation is OperationKind.CONTINUE:
        values["continuation_source"] = _member()
    if operation in (OperationKind.PUBLISH, OperationKind.RECONCILE):
        values["requested_network_mode"] = None
        values["requested_vpn_parallelism"] = 0
        values["terminal_handoff"] = _member(member_path="handoff/terminal.json")
    if operation in (OperationKind.DAILY_BUILD, OperationKind.MONTHLY_BUILD):
        values["parent_readback"] = _member(member_path="readback/n.json")
        values["parent_private_capture"] = _member(member_path="private/n.json")
        values["parent_data_green"] = _member(member_path="data-green/n.json")
    if operation is OperationKind.DATA_GREEN_CLOSEOUT:
        values["requested_network_mode"] = None
        values["requested_vpn_parallelism"] = 0
        values["remote_readback"] = _member(member_path="readback/n.json")
        values["human_verification_receipt"] = _member(member_path="human/receipt.json")
    values.update(overrides)
    return OperationAuthorityV1(**values)


def _runtime_for(authority: OperationAuthorityV1) -> ActionsRuntimeView:
    return ActionsRuntimeView(
        repository=authority.repository,
        run_id=authority.run_id,
        run_attempt=authority.run_attempt,
        event=authority.event,
        actor=authority.actor,
        trusted_ref=authority.trusted_ref,
        workflow_commit_sha=authority.workflow_commit_sha,
        source_sha=authority.source_sha,
        workflow_content_sha256=authority.workflow_content_sha256,
    )


def test_operation_kind_is_exact() -> None:
    assert {kind.value for kind in OperationKind} == {
        "targeted_smoke",
        "extract",
        "continue",
        "publish",
        "reconcile",
        "daily_build",
        "monthly_build",
        "data_green_closeout",
    }


@pytest.mark.parametrize("operation", _ALL_OPERATIONS)
def test_positive_fixture_round_trips_and_revalidates(operation: OperationKind) -> None:
    authority = _authority(operation)
    assert authority.authority_sha256
    payload = authority.to_dict()
    assert payload["schema_version"] == OPERATION_AUTHORITY_SCHEMA_VERSION
    parsed = OperationAuthorityV1.from_dict(payload)
    assert parsed == authority
    assert parsed.authority_sha256 == authority.authority_sha256
    assert parsed.require_current_actions_runtime(_runtime_for(authority)) is parsed


def test_digest_is_deterministic_and_identity_sensitive() -> None:
    first = _authority(OperationKind.EXTRACT)
    second = _authority(OperationKind.EXTRACT)
    assert first.authority_sha256 == second.authority_sha256
    mutated = _authority(OperationKind.EXTRACT, actor="someone-else")
    assert mutated.authority_sha256 != first.authority_sha256


def test_serialized_status_cannot_confer_authority() -> None:
    authority = _authority(OperationKind.PUBLISH)
    payload = authority.to_dict()
    forged = dict(payload)
    forged["status"] = "authorized"
    with pytest.raises(OperationAuthorityError, match="unexpected=status"):
        OperationAuthorityV1.from_dict(forged)
    tampered = dict(payload)
    tampered["authority_sha256"] = "f" * 64
    with pytest.raises(OperationAuthorityError, match="recomputed"):
        OperationAuthorityV1.from_dict(tampered)
    with pytest.raises(OperationAuthorityError, match="does not match"):
        replace(authority, authority_sha256="f" * 64)


def test_exact_key_serialization_enforced() -> None:
    payload = _authority(OperationKind.EXTRACT).to_dict()
    missing = dict(payload)
    del missing["chain_id"]
    with pytest.raises(OperationAuthorityError, match="missing=chain_id"):
        OperationAuthorityV1.from_dict(missing)
    wrong_version = dict(payload)
    wrong_version["schema_version"] = 99
    with pytest.raises(OperationAuthorityError, match="schema version"):
        OperationAuthorityV1.from_dict(wrong_version)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("repository", "other/repo"),
        ("run_id", 999),
        ("run_attempt", 2),
        ("event", "push"),
        ("actor", "someone-else"),
        ("trusted_ref", "refs/heads/other"),
        ("workflow_commit_sha", "f" * 40),
        ("source_sha", "f" * 40),
        ("workflow_content_sha256", "f" * 64),
    ],
)
def test_runtime_mismatch_fails_closed(field: str, value: object) -> None:
    authority = _authority(OperationKind.EXTRACT)
    runtime = replace(_runtime_for(authority), **{field: value})
    with pytest.raises(OperationAuthorityError, match="current Actions runtime"):
        authority.require_current_actions_runtime(runtime)


def test_non_dispatch_event_rejected() -> None:
    with pytest.raises(OperationAuthorityError, match="workflow_dispatch"):
        _authority(OperationKind.EXTRACT, event="push")
    authority = _authority(OperationKind.EXTRACT)
    runtime = replace(_runtime_for(authority), event="schedule")
    with pytest.raises(OperationAuthorityError, match="current Actions runtime"):
        authority.require_current_actions_runtime(runtime)


class TestTargetedSmokeInvariants:
    def test_direct_mode_rejected(self) -> None:
        with pytest.raises(OperationAuthorityError, match="VPN-only"):
            _authority(
                OperationKind.TARGETED_SMOKE,
                requested_network_mode=NetworkMode.AUTO,
                requested_direct_parallelism=1,
            )

    def test_multiple_vpn_lanes_rejected(self) -> None:
        with pytest.raises(OperationAuthorityError, match="one VPN lane"):
            _authority(OperationKind.TARGETED_SMOKE, requested_vpn_parallelism=2)

    def test_direct_slots_rejected(self) -> None:
        with pytest.raises(OperationAuthorityError, match="zero direct"):
            _authority(OperationKind.TARGETED_SMOKE, requested_direct_parallelism=1)

    def test_multiple_iterations_rejected(self) -> None:
        with pytest.raises(OperationAuthorityError, match="one iteration"):
            _authority(OperationKind.TARGETED_SMOKE, max_iterations=2)

    def test_retry_rejected(self) -> None:
        with pytest.raises(OperationAuthorityError, match="retry"):
            _authority(OperationKind.TARGETED_SMOKE, retry_pipeline_failures=True)

    def test_re_extraction_rejected(self) -> None:
        with pytest.raises(OperationAuthorityError, match="re-extract"):
            _authority(OperationKind.TARGETED_SMOKE, allow_re_extraction=True)

    def test_multiple_manifest_lanes_rejected(self) -> None:
        with pytest.raises(OperationAuthorityError, match="one manifest lane"):
            _authority(OperationKind.TARGETED_SMOKE, manifest_lane_count=2)

    def test_continuation_source_rejected(self) -> None:
        with pytest.raises(OperationAuthorityError, match="continuation source"):
            _authority(
                OperationKind.TARGETED_SMOKE,
                continuation_source=_member(),
            )

    def test_handoff_rejected(self) -> None:
        with pytest.raises(OperationAuthorityError, match="terminal handoff"):
            _authority(OperationKind.TARGETED_SMOKE, terminal_handoff=_member())


class TestExtractInvariants:
    def test_continuation_source_rejected(self) -> None:
        with pytest.raises(OperationAuthorityError, match="fresh chain"):
            _authority(OperationKind.EXTRACT, continuation_source=_member())

    def test_zero_vpn_parallelism_rejected(self) -> None:
        with pytest.raises(OperationAuthorityError, match="parallelism"):
            _authority(OperationKind.EXTRACT, requested_vpn_parallelism=0)

    def test_seven_vpn_lanes_rejected(self) -> None:
        with pytest.raises(OperationAuthorityError, match="parallelism"):
            _authority(OperationKind.EXTRACT, requested_vpn_parallelism=7)

    def test_direct_capacity_with_vpn_mode_rejected(self) -> None:
        with pytest.raises(OperationAuthorityError, match="direct capacity"):
            _authority(
                OperationKind.EXTRACT,
                requested_direct_parallelism=1,
            )

    def test_unbounded_direct_fallback_rejected(self) -> None:
        with pytest.raises(OperationAuthorityError, match="direct fallback"):
            _authority(
                OperationKind.EXTRACT,
                requested_network_mode=NetworkMode.AUTO,
                requested_direct_parallelism=DIRECT_PARALLELISM_LIMIT + 1,
            )

    def test_bounded_auto_direct_accepted(self) -> None:
        authority = _authority(
            OperationKind.EXTRACT,
            requested_network_mode=NetworkMode.AUTO,
            requested_direct_parallelism=2,
        )
        assert authority.requested_network_mode is NetworkMode.AUTO

    def test_handoff_rejected(self) -> None:
        with pytest.raises(OperationAuthorityError, match="terminal handoff"):
            _authority(OperationKind.EXTRACT, terminal_handoff=_member())


class TestContinueInvariants:
    def test_missing_source_rejected(self) -> None:
        with pytest.raises(OperationAuthorityError, match="continuation source"):
            _authority(OperationKind.CONTINUE, continuation_source=None)

    def test_same_run_source_rejected(self) -> None:
        with pytest.raises(OperationAuthorityError, match="distinct from the current run"):
            _authority(OperationKind.CONTINUE, continuation_source=_member(run_id=_RUN_ID))

    def test_foreign_repository_member_rejected(self) -> None:
        with pytest.raises(OperationAuthorityError, match="authority repository"):
            _authority(
                OperationKind.CONTINUE,
                continuation_source=_member(repository="other/repo"),
            )

    def test_seven_vpn_lanes_rejected(self) -> None:
        with pytest.raises(OperationAuthorityError, match="parallelism"):
            _authority(
                OperationKind.CONTINUE,
                requested_vpn_parallelism=VPN_PARALLELISM_LIMIT + 1,
                continuation_source=_member(),
            )


class TestPublishReconcileInvariants:
    @pytest.mark.parametrize("operation", [OperationKind.PUBLISH, OperationKind.RECONCILE])
    def test_missing_handoff_rejected(self, operation: OperationKind) -> None:
        with pytest.raises(OperationAuthorityError, match="terminal handoff member"):
            _authority(operation, terminal_handoff=None)

    @pytest.mark.parametrize("operation", [OperationKind.PUBLISH, OperationKind.RECONCILE])
    def test_network_mode_rejected(self, operation: OperationKind) -> None:
        with pytest.raises(OperationAuthorityError, match="network mode"):
            _authority(operation, requested_network_mode=NetworkMode.VPN)

    @pytest.mark.parametrize("operation", [OperationKind.PUBLISH, OperationKind.RECONCILE])
    def test_extraction_parallelism_rejected(self, operation: OperationKind) -> None:
        with pytest.raises(OperationAuthorityError, match="parallelism"):
            _authority(operation, requested_vpn_parallelism=2)

    @pytest.mark.parametrize("operation", [OperationKind.PUBLISH, OperationKind.RECONCILE])
    def test_continuation_source_rejected(self, operation: OperationKind) -> None:
        with pytest.raises(OperationAuthorityError, match="continuation source"):
            _authority(operation, continuation_source=_member())

    @pytest.mark.parametrize("operation", [OperationKind.PUBLISH, OperationKind.RECONCILE])
    def test_retry_controls_rejected(self, operation: OperationKind) -> None:
        with pytest.raises(OperationAuthorityError, match="retry"):
            _authority(operation, retry_pipeline_failures=True)

    @pytest.mark.parametrize("operation", [OperationKind.PUBLISH, OperationKind.RECONCILE])
    def test_multiple_iterations_rejected(self, operation: OperationKind) -> None:
        with pytest.raises(OperationAuthorityError, match="iterations"):
            _authority(operation, max_iterations=2)


class TestSuccessorBuildInvariants:
    @pytest.mark.parametrize("operation", [OperationKind.DAILY_BUILD, OperationKind.MONTHLY_BUILD])
    @pytest.mark.parametrize(
        "drop", ["parent_readback", "parent_private_capture", "parent_data_green"]
    )
    def test_missing_parent_member_rejected(self, operation: OperationKind, drop: str) -> None:
        with pytest.raises(OperationAuthorityError, match="requires exact"):
            _authority(operation, **{drop: None})

    @pytest.mark.parametrize("operation", [OperationKind.DAILY_BUILD, OperationKind.MONTHLY_BUILD])
    def test_handoff_rejected(self, operation: OperationKind) -> None:
        with pytest.raises(OperationAuthorityError, match="handoff member"):
            _authority(operation, terminal_handoff=_member())


class TestDataGreenCloseoutInvariants:
    def test_missing_readback_rejected(self) -> None:
        with pytest.raises(OperationAuthorityError, match="remote readback member"):
            _authority(OperationKind.DATA_GREEN_CLOSEOUT, remote_readback=None)

    def test_missing_human_receipt_rejected(self) -> None:
        with pytest.raises(OperationAuthorityError, match="human verification receipt member"):
            _authority(OperationKind.DATA_GREEN_CLOSEOUT, human_verification_receipt=None)

    def test_network_mode_rejected(self) -> None:
        with pytest.raises(OperationAuthorityError, match="network mode"):
            _authority(
                OperationKind.DATA_GREEN_CLOSEOUT,
                requested_network_mode=NetworkMode.VPN,
            )

    def test_handoff_rejected(self) -> None:
        with pytest.raises(OperationAuthorityError, match="handoff member"):
            _authority(OperationKind.DATA_GREEN_CLOSEOUT, terminal_handoff=_member())


class TestExactArtifactMember:
    def test_attempt_is_never_inferred_from_artifact_name(self) -> None:
        member = _member(
            artifact_name="manifest-run101-attempt77",
            run_attempt=2,
        )
        assert member.run_attempt == 2
        parsed = ExactArtifactMemberV1.from_dict(member.to_dict())
        assert parsed.run_attempt == 2

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("run_id", 0),
            ("run_id", -1),
            ("run_attempt", 0),
            ("artifact_id", 0),
            ("artifact_digest", "d" * 64),
            ("artifact_digest", "sha256:" + "D" * 64),
            ("artifact_digest", "sha256:" + "d" * 63),
            ("artifact_name", ""),
            ("member_sha256", "e" * 63),
            ("member_size_bytes", -1),
            ("artifact_size_bytes", -1),
        ],
    )
    def test_identity_fields_fail_closed(self, field: str, value: object) -> None:
        with pytest.raises(OperationAuthorityError):
            _member(**{field: value})

    @pytest.mark.parametrize(
        "path",
        [
            "/absolute/path.json",
            "../escape.json",
            "nested/../../escape.json",
            "back\\slash.json",
            "trailing/",
            "double//slash.json",
            "",
            " dot/./relative.json",
        ],
    )
    def test_unsafe_member_paths_rejected(self, path: str) -> None:
        with pytest.raises(OperationAuthorityError, match="member_path"):
            _member(member_path=path)


def test_identity_shape_validation() -> None:
    with pytest.raises(OperationAuthorityError, match="owner/name"):
        _authority(OperationKind.EXTRACT, repository="not-a-repository")
    with pytest.raises(OperationAuthorityError, match="workflow file path"):
        _authority(OperationKind.EXTRACT, workflow_path="workflows/main.yml")
    with pytest.raises(OperationAuthorityError, match="commit SHA"):
        _authority(OperationKind.EXTRACT, source_sha="short")
    with pytest.raises(OperationAuthorityError, match="SHA-256"):
        _authority(OperationKind.EXTRACT, workflow_content_sha256="z" * 64)


def test_boolean_fields_are_exact() -> None:
    with pytest.raises(OperationAuthorityError, match="exact boolean"):
        _authority(
            OperationKind.EXTRACT,
            retry_pipeline_failures=1,  # type: ignore[arg-type]
        )
    with pytest.raises(OperationAuthorityError, match="exact boolean"):
        _authority(
            OperationKind.EXTRACT,
            allow_re_extraction=None,  # type: ignore[arg-type]
        )


def test_unknown_operation_string_rejected() -> None:
    payload = _authority(OperationKind.EXTRACT).to_dict()
    payload["operation"] = "rerun"
    with pytest.raises(OperationAuthorityError, match="OperationKind"):
        OperationAuthorityV1.from_dict(payload)


def test_workflow_default_vpn_parallelism_is_two() -> None:
    assert _authority(OperationKind.EXTRACT).requested_vpn_parallelism == VPN_PARALLELISM_DEFAULT


def test_shared_member_round_trip_preserves_identity() -> None:
    """J1 join: the flat member must convert to/from the shared contract."""

    from nbadb.contracts.actions_artifact import ArtifactMemberIdentityV1

    flat = _member()
    shared = flat.to_shared_member()
    assert isinstance(shared, ArtifactMemberIdentityV1)
    assert shared.artifact.repository == flat.repository
    assert shared.artifact.run_id == flat.run_id
    assert shared.artifact.run_attempt == flat.run_attempt
    assert shared.artifact.artifact_id == flat.artifact_id
    assert shared.artifact.artifact_name == flat.artifact_name
    assert shared.artifact.artifact_digest == flat.artifact_digest
    assert shared.artifact.artifact_size_bytes == flat.artifact_size_bytes
    assert shared.member_path == flat.member_path
    assert shared.member_sha256 == flat.member_sha256
    assert shared.member_size_bytes == flat.member_size_bytes
    assert ExactArtifactMemberV1.from_shared_member(shared) == flat
