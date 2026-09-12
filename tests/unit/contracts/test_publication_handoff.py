from __future__ import annotations

import pytest

from nbadb.contracts.actions_artifact import (
    ActionsArtifactIdentityV1,
    ArtifactMemberIdentityV1,
)
from nbadb.contracts.publication_handoff import (
    PUBLICATION_HANDOFF_SCHEMA_VERSION,
    CheckpointBindingV1,
    PublicationHandoffError,
    TerminalPublicationHandoffV1,
)

_REPO = "owner/nbadb"
_OTHER_REPO = "owner/other"
_GIT_SHA = "1" * 40
_HEX_A = "a" * 64
_HEX_B = "b" * 64


def _artifact(
    name: str,
    *,
    artifact_id: int,
    run_id: int = 901,
    run_attempt: int = 1,
    repository: str = _REPO,
) -> ActionsArtifactIdentityV1:
    return ActionsArtifactIdentityV1(
        repository=repository,
        run_id=run_id,
        run_attempt=run_attempt,
        artifact_id=artifact_id,
        artifact_name=name,
        artifact_digest=f"sha256:{_HEX_A}",
        artifact_size_bytes=1024,
    )


def _member(
    artifact: ActionsArtifactIdentityV1,
    path: str = "evidence/manifest.json",
) -> ArtifactMemberIdentityV1:
    return ArtifactMemberIdentityV1(
        artifact=artifact,
        member_path=path,
        member_sha256=_HEX_A,
        member_size_bytes=64,
    )


def _checkpoint(
    *,
    state: str = "committed",
    run_id: int = 901,
    run_attempt: int = 1,
    artifact_name: str = "extraction-checkpoint",
) -> CheckpointBindingV1:
    return CheckpointBindingV1(
        state=state,
        transaction_id="txn-0001",
        transaction_sha256=_HEX_A,
        artifact=_artifact(
            artifact_name,
            artifact_id=11,
            run_id=run_id,
            run_attempt=run_attempt,
        ),
    )


def _handoff_kwargs(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "producer_repository": _REPO,
        "workflow_path": ".github/workflows/full-extraction.yml",
        "workflow_content_sha256": _HEX_A,
        "workflow_sha": _GIT_SHA,
        "source_sha": _GIT_SHA,
        "run_id": 901,
        "run_attempt": 1,
        "chain_id": "chain-1",
        "terminal_iteration": 3,
        "operation_authority_sha256": _HEX_A,
        "next_manifest_member": _member(
            _artifact("next-iteration-manifest", artifact_id=12), "manifests/next.json"
        ),
        "checkpoint": _checkpoint(),
        "candidate_artifact": _artifact("sanitized-public-candidate", artifact_id=13),
        "candidate_inventory_sha256": _HEX_A,
        "candidate_tree_sha256": _HEX_A,
        "prepublication_admission_sha256": _HEX_A,
        "public_disposition_sha256": _HEX_B,
        "metadata_sha256": _HEX_A,
        "private_capture_assurance_sha256": _HEX_A,
        "successor": False,
        "private_baseline_member": None,
    }
    values.update(overrides)
    return values


def _successor_kwargs(**overrides: object) -> dict[str, object]:
    parent_member = _member(
        _artifact("parent-private-baseline", artifact_id=21, run_id=800, run_attempt=2),
        "private/baseline-1.json",
    )
    values: dict[str, object] = {
        "workflow_path": ".github/workflows/daily-update.yml",
        "successor": True,
        "private_baseline_member": parent_member,
    }
    values.update(overrides)
    return _handoff_kwargs(**values)


class TestPositiveFixtures:
    def test_full_extraction_handoff_builds_verifies_and_round_trips(self) -> None:
        handoff = TerminalPublicationHandoffV1.build(**_handoff_kwargs())
        handoff.verify()
        payload = handoff.to_payload()
        assert payload["schema_version"] == PUBLICATION_HANDOFF_SCHEMA_VERSION
        parsed = TerminalPublicationHandoffV1.from_payload(payload)
        assert parsed == handoff
        assert parsed.handoff_sha256 == handoff.handoff_sha256

    def test_successor_handoff_binds_parent_run_private_baseline(self) -> None:
        handoff = TerminalPublicationHandoffV1.build(**_successor_kwargs())
        assert handoff.successor is True
        # The parent-owned member intentionally names a different run.
        assert handoff.private_baseline_member is not None
        assert handoff.private_baseline_member.artifact.run_id == 800
        handoff.verify()
        parsed = TerminalPublicationHandoffV1.from_payload(handoff.to_payload())
        assert parsed == handoff

    def test_build_is_deterministic(self) -> None:
        first = TerminalPublicationHandoffV1.build(**_handoff_kwargs())
        second = TerminalPublicationHandoffV1.build(**_handoff_kwargs())
        assert first.handoff_sha256 == second.handoff_sha256

    def test_checkpoint_binding_round_trips(self) -> None:
        checkpoint = _checkpoint()
        parsed = CheckpointBindingV1.from_payload(checkpoint.to_payload())
        assert parsed == checkpoint


class TestCheckpointInvariants:
    @pytest.mark.parametrize("state", ["candidate", "built", "uploaded_verified"])
    def test_noncommitted_checkpoint_rejected(self, state: str) -> None:
        with pytest.raises(PublicationHandoffError, match="committed checkpoint"):
            TerminalPublicationHandoffV1.build(
                **_handoff_kwargs(checkpoint=_checkpoint(state=state))
            )

    def test_unknown_checkpoint_state_rejected(self) -> None:
        with pytest.raises(PublicationHandoffError, match="checkpoint.state"):
            CheckpointBindingV1(
                state="draft",
                transaction_id="txn-0001",
                transaction_sha256=_HEX_A,
                artifact=_artifact("extraction-checkpoint", artifact_id=11),
            )

    def test_checkpoint_owner_attempt_mismatch_rejected(self) -> None:
        with pytest.raises(PublicationHandoffError, match="run 901/attempt 2"):
            TerminalPublicationHandoffV1.build(
                **_handoff_kwargs(checkpoint=_checkpoint(run_attempt=2))
            )

    def test_checkpoint_owner_run_mismatch_rejected(self) -> None:
        with pytest.raises(PublicationHandoffError, match="run 800/attempt 1"):
            TerminalPublicationHandoffV1.build(
                **_handoff_kwargs(checkpoint=_checkpoint(run_id=800))
            )

    def test_checkpoint_transaction_digest_shape(self) -> None:
        with pytest.raises(PublicationHandoffError, match="transaction_sha256"):
            CheckpointBindingV1(
                state="committed",
                transaction_id="txn-0001",
                transaction_sha256="nothex",
                artifact=_artifact("extraction-checkpoint", artifact_id=11),
            )


class TestArtifactJoins:
    def test_manifest_artifact_owner_run_mismatch_rejected(self) -> None:
        member = _member(_artifact("next-iteration-manifest", artifact_id=12, run_id=800))
        with pytest.raises(PublicationHandoffError, match="next_manifest_member.artifact"):
            TerminalPublicationHandoffV1.build(**_handoff_kwargs(next_manifest_member=member))

    def test_manifest_artifact_owner_attempt_mismatch_rejected(self) -> None:
        member = _member(_artifact("next-iteration-manifest", artifact_id=12, run_attempt=2))
        with pytest.raises(PublicationHandoffError, match="attempt 2"):
            TerminalPublicationHandoffV1.build(**_handoff_kwargs(next_manifest_member=member))

    def test_candidate_artifact_owner_mismatch_rejected(self) -> None:
        with pytest.raises(PublicationHandoffError, match="candidate_artifact"):
            TerminalPublicationHandoffV1.build(
                **_handoff_kwargs(
                    candidate_artifact=_artifact(
                        "sanitized-public-candidate", artifact_id=13, run_id=800
                    )
                )
            )

    @pytest.mark.parametrize(
        ("field", "artifact_factory"),
        [
            (
                "next_manifest_member",
                lambda: _member(_artifact("next-manifest-latest", artifact_id=12)),
            ),
            (
                "checkpoint",
                lambda: _checkpoint(artifact_name="checkpoint-current"),
            ),
        ],
    )
    def test_mutable_artifact_name_rejected(self, field: str, artifact_factory: object) -> None:
        with pytest.raises(PublicationHandoffError, match="mutable"):
            TerminalPublicationHandoffV1.build(**_handoff_kwargs(**{field: artifact_factory()}))

    def test_mutable_candidate_name_rejected(self) -> None:
        with pytest.raises(PublicationHandoffError, match="mutable"):
            TerminalPublicationHandoffV1.build(
                **_handoff_kwargs(
                    candidate_artifact=_artifact("sanitized-candidate-latest", artifact_id=13)
                )
            )

    def test_repository_mismatch_rejected(self) -> None:
        with pytest.raises(PublicationHandoffError, match="owner/other"):
            TerminalPublicationHandoffV1.build(
                **_handoff_kwargs(
                    candidate_artifact=_artifact(
                        "sanitized-public-candidate",
                        artifact_id=13,
                        repository=_OTHER_REPO,
                    )
                )
            )

    def test_parent_member_repository_mismatch_rejected(self) -> None:
        parent_member = _member(
            _artifact(
                "parent-private-baseline",
                artifact_id=21,
                run_id=800,
                repository=_OTHER_REPO,
            )
        )
        with pytest.raises(PublicationHandoffError, match="private_baseline_member.artifact"):
            TerminalPublicationHandoffV1.build(
                **_successor_kwargs(private_baseline_member=parent_member)
            )

    def test_parent_member_mutable_name_rejected(self) -> None:
        parent_member = _member(_artifact("parent-baseline-latest", artifact_id=21, run_id=800))
        with pytest.raises(PublicationHandoffError, match="mutable"):
            TerminalPublicationHandoffV1.build(
                **_successor_kwargs(private_baseline_member=parent_member)
            )


class TestSuccessorParent:
    def test_successor_without_private_parent_rejected(self) -> None:
        with pytest.raises(PublicationHandoffError, match="private-baseline"):
            TerminalPublicationHandoffV1.build(**_successor_kwargs(private_baseline_member=None))

    def test_non_successor_with_private_parent_rejected(self) -> None:
        parent_member = _member(_artifact("parent-private-baseline", artifact_id=21))
        with pytest.raises(PublicationHandoffError, match="reserved for successor"):
            TerminalPublicationHandoffV1.build(
                **_handoff_kwargs(private_baseline_member=parent_member)
            )

    def test_successor_flag_must_be_bool(self) -> None:
        with pytest.raises(PublicationHandoffError, match="successor"):
            TerminalPublicationHandoffV1.build(**_handoff_kwargs(successor="yes"))


class TestDigestJoinsAndTamper:
    def test_payload_digest_substitution_fails_seal(self) -> None:
        handoff = TerminalPublicationHandoffV1.build(**_handoff_kwargs())
        payload = handoff.to_payload()
        payload["public_disposition_sha256"] = _HEX_A
        with pytest.raises(PublicationHandoffError, match="digest mismatch"):
            TerminalPublicationHandoffV1.from_payload(payload)

    def test_payload_handoff_digest_tamper_rejected(self) -> None:
        handoff = TerminalPublicationHandoffV1.build(**_handoff_kwargs())
        payload = handoff.to_payload()
        payload["handoff_sha256"] = _HEX_B
        with pytest.raises(PublicationHandoffError, match="digest mismatch"):
            TerminalPublicationHandoffV1.from_payload(payload)

    def test_payload_attempt_substitution_fails_seal(self) -> None:
        handoff = TerminalPublicationHandoffV1.build(**_handoff_kwargs())
        payload = handoff.to_payload()
        payload["run_attempt"] = 2
        with pytest.raises(PublicationHandoffError, match="digest mismatch"):
            TerminalPublicationHandoffV1.from_payload(payload)

    def test_payload_schema_version_rejected(self) -> None:
        handoff = TerminalPublicationHandoffV1.build(**_handoff_kwargs())
        payload = handoff.to_payload()
        payload["schema_version"] = 99
        with pytest.raises(PublicationHandoffError, match="schema version"):
            TerminalPublicationHandoffV1.from_payload(payload)


class TestPayloadStrictness:
    def test_missing_key_rejected(self) -> None:
        handoff = TerminalPublicationHandoffV1.build(**_handoff_kwargs())
        payload = handoff.to_payload()
        del payload["metadata_sha256"]
        with pytest.raises(PublicationHandoffError, match="missing=\\['metadata_sha256'\\]"):
            TerminalPublicationHandoffV1.from_payload(payload)

    def test_extra_key_rejected(self) -> None:
        handoff = TerminalPublicationHandoffV1.build(**_handoff_kwargs())
        payload = handoff.to_payload()
        payload["operator_override"] = True
        with pytest.raises(PublicationHandoffError, match="extra=\\['operator_override'\\]"):
            TerminalPublicationHandoffV1.from_payload(payload)

    def test_build_missing_field_rejected(self) -> None:
        values = _handoff_kwargs()
        del values["chain_id"]
        with pytest.raises(PublicationHandoffError, match="missing=\\['chain_id'\\]"):
            TerminalPublicationHandoffV1.build(**values)

    def test_build_extra_field_rejected(self) -> None:
        with pytest.raises(PublicationHandoffError, match="extra=\\['admitted'\\]"):
            TerminalPublicationHandoffV1.build(**_handoff_kwargs(admitted=True))


class TestFieldShapes:
    def test_workflow_path_outside_workflows_rejected(self) -> None:
        with pytest.raises(PublicationHandoffError, match="workflow_path"):
            TerminalPublicationHandoffV1.build(
                **_handoff_kwargs(workflow_path="workflows/full-extraction.yml")
            )

    def test_workflow_sha_shape_rejected(self) -> None:
        with pytest.raises(PublicationHandoffError, match="workflow_sha"):
            TerminalPublicationHandoffV1.build(**_handoff_kwargs(workflow_sha="short"))

    def test_public_disposition_digest_shape_rejected(self) -> None:
        with pytest.raises(PublicationHandoffError, match="public_disposition_sha256"):
            TerminalPublicationHandoffV1.build(
                **_handoff_kwargs(public_disposition_sha256="sha256:abc")
            )

    def test_run_attempt_must_be_positive(self) -> None:
        with pytest.raises(PublicationHandoffError, match="run_attempt"):
            TerminalPublicationHandoffV1.build(**_handoff_kwargs(run_attempt=0))

    def test_terminal_iteration_must_be_positive(self) -> None:
        with pytest.raises(PublicationHandoffError, match="terminal_iteration"):
            TerminalPublicationHandoffV1.build(**_handoff_kwargs(terminal_iteration=0))

    def test_run_id_bool_rejected(self) -> None:
        with pytest.raises(PublicationHandoffError, match="run_id"):
            TerminalPublicationHandoffV1.build(**_handoff_kwargs(run_id=True))

    def test_producer_repository_shape_rejected(self) -> None:
        with pytest.raises(PublicationHandoffError, match="producer_repository"):
            TerminalPublicationHandoffV1.build(**_handoff_kwargs(producer_repository="owner"))
