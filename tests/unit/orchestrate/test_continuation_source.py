"""Unit tests for the exact continuation-source authority."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import zipfile
from dataclasses import replace
from typing import Any

import pytest

from nbadb.contracts.actions_artifact import ArtifactMemberIdentityV1
from nbadb.orchestrate.checkpoint_contract import (
    CheckpointArtifactReceipt,
    CheckpointTransaction,
    CheckpointW2AuthorityIdentity,
)
from nbadb.orchestrate.continuation_source import (
    ContinuationDispatchInputs,
    ContinuationSourceError,
    continuation_inputs_from_env,
    verify_continuation_source,
)
from nbadb.orchestrate.public_value_authority_store import PUBLIC_VALUE_AUTHORITY_TABLES
from nbadb.orchestrate.w2_database_assurance import W2DatabaseAuthorityReceiptV1
from nbadb.orchestrate.w2_operation_store import RAW_NBA_API_W2_OPERATION_TABLE

_REPO = "owner/nbadb"
_CHAIN = "chain-42"
_SOURCE_SHA = "1" * 40
_MEMBER = "manifests/next.json"
_HEX = "a" * 64


def _w2_authority() -> CheckpointW2AuthorityIdentity:
    relation_counts = tuple(
        sorted(
            (table_name, 0)
            for table_name in (*PUBLIC_VALUE_AUTHORITY_TABLES, RAW_NBA_API_W2_OPERATION_TABLE)
        )
    )
    database_authority = W2DatabaseAuthorityReceiptV1.build(
        w2_required_logical_call_count=0,
        w2_source_call_admission_inventory_sha256="4" * 64,
        raw_authority_v2_bundle_count=0,
        raw_authority_v2_bundle_inventory_sha256="5" * 64,
        raw_authority_v2_persistence_receipt_inventory_sha256="6" * 64,
        w2_publication_receipt_count=0,
        w2_publication_receipt_inventory_sha256="7" * 64,
        w2_exact_six_schema_inventory_sha256="8" * 64,
        w2_relation_row_counts=relation_counts,
        w2_relation_row_count=0,
        w2_relation_inventory_sha256="9" * 64,
    )
    return CheckpointW2AuthorityIdentity(
        database_authority=database_authority,
        database_authority_sha256=database_authority.receipt_sha256,
        expected_call_count=0,
        expected_call_inventory_sha256="0" * 64,
        database_authority_closed=True,
    )


def committed_checkpoint_payload(
    *, chain_id: str, source_sha: str, generation: int, run_id: int = 500, attempt: int = 2
) -> dict[str, object]:
    built = CheckpointTransaction.candidate(
        chain_id=chain_id,
        source_sha=source_sha,
        generation=generation,
        artifact_name=f"full-extraction-checkpoint-{chain_id}-iter-{generation}",
        lane_contracts=[{"lane_id": "fixture-lane", "coverage_units_hash": "0" * 64}],
        coverage_fingerprint="e" * 64,
    ).mark_built(
        database_sha256="1" * 64,
        report_sha256="2" * 64,
        w2_authority=_w2_authority(),
    )
    assert built.build is not None
    receipt = CheckpointArtifactReceipt(
        artifact_id=77,
        artifact_run_id=run_id,
        artifact_run_attempt=attempt,
        artifact_name=built.artifact_name,
        artifact_digest=f"sha256:{_HEX}",
        artifact_size_bytes=4096,
        database_sha256=built.build.database_sha256,
        report_sha256=built.build.report_sha256,
        chain_id=chain_id,
        source_sha=source_sha,
        generation=generation,
        coverage_fingerprint="e" * 64,
        lane_inventory_sha256=built.identity.coverage.lane_inventory_sha256,
        w2_authority_identity_sha256=built.build.w2_authority.identity_sha256,
    )
    return built.mark_uploaded_verified(receipt).commit().to_dict()


def _inputs(**overrides: object) -> ContinuationDispatchInputs:
    values: dict[str, object] = {
        "repository": _REPO,
        "source_run_id": 500,
        "source_run_attempt": 2,
        "manifest_artifact_name": f"next-iteration-manifest-{_CHAIN}-iter-3",
        "manifest_artifact_id": 77,
        "manifest_artifact_digest": f"sha256:{_HEX}",
        "chain_id": _CHAIN,
        "source_sha": _SOURCE_SHA,
        "expected_member_path": _MEMBER,
    }
    values.update(overrides)
    return ContinuationDispatchInputs(**values)  # type: ignore[arg-type]


class _FakeTransport:
    def __init__(
        self,
        *,
        artifact: dict[str, Any],
        archive: bytes,
        run: dict[str, Any] | None = None,
    ) -> None:
        self._artifact = artifact
        self._archive = archive
        owner = artifact.get("workflow_run")
        owner_run_id = owner.get("id") if isinstance(owner, dict) else 500
        self._run = run or {
            "id": owner_run_id,
            "run_attempt": 2,
            "event": "workflow_dispatch",
            "head_sha": _SOURCE_SHA,
        }

    def artifact(self, repository: str, artifact_id: int) -> dict[str, Any]:
        return self._artifact

    def workflow_run(self, repository: str, run_id: int) -> dict[str, Any]:
        return self._run

    def download(self, repository: str, artifact_id: int) -> bytes:
        return self._archive


def _fixture_transport(inputs: ContinuationDispatchInputs) -> _FakeTransport:
    artifact_json = {
        "id": inputs.manifest_artifact_id,
        "name": inputs.manifest_artifact_name,
        "workflow_run": {"id": inputs.source_run_id},
        "digest": inputs.manifest_artifact_digest,
        "size_in_bytes": 4096,
        "expired": False,
    }
    transaction = committed_checkpoint_payload(
        chain_id=inputs.chain_id,
        source_sha=inputs.source_sha,
        generation=3,
    )
    member_bytes = json.dumps(transaction, sort_keys=True, separators=(",", ":")).encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(_MEMBER, member_bytes)
        archive.writestr("evidence/report.json", b"{}")
    archive_bytes = buffer.getvalue()
    digest = f"sha256:{hashlib.sha256(archive_bytes).hexdigest()}"
    return _FakeTransport(
        artifact={
            **artifact_json,
            "digest": digest,
            "size_in_bytes": len(archive_bytes),
        },
        archive=archive_bytes,
        run={
            "id": inputs.source_run_id,
            "run_attempt": inputs.source_run_attempt,
            "event": "workflow_dispatch",
            "head_sha": inputs.source_sha,
        },
    )


def _bound_inputs(inputs: ContinuationDispatchInputs) -> ContinuationDispatchInputs:
    """Rebind the digest to the fixture archive the transport serves."""

    transport = _fixture_transport(inputs)
    digest = transport.artifact(_REPO, inputs.manifest_artifact_id)["digest"]
    return replace(inputs, manifest_artifact_digest=digest)


class TestHappyPath:
    def test_verifies_exact_source_and_returns_member_and_transaction(self) -> None:
        inputs = _bound_inputs(_inputs())
        transport = _fixture_transport(inputs)
        verified = verify_continuation_source(inputs, transport, current_run_id=501)
        assert isinstance(verified.member, ArtifactMemberIdentityV1)
        assert verified.member.artifact.run_id == 500
        assert verified.member.artifact.run_attempt == 2
        assert verified.member.artifact.artifact_id == 77
        assert verified.transaction.identity.chain_id == _CHAIN
        assert verified.transaction.identity.generation == 3
        assert verified.member_payload_sha256 == verified.member.member_sha256

    def test_attempt_is_used_from_dispatch_not_the_name(self) -> None:
        inputs = _bound_inputs(_inputs())
        transport = _fixture_transport(inputs)
        verified = verify_continuation_source(inputs, transport, current_run_id=501)
        assert verified.member.artifact.run_attempt == 2


class TestInputContract:
    def test_all_or_none_is_enforced_by_env_builder(self) -> None:
        env = {
            "FULL_EXTRACTION_RESUME_SOURCE_RUN_ID": "500",
            "FULL_EXTRACTION_RESUME_SOURCE_RUN_ATTEMPT": "2",
            "FULL_EXTRACTION_RESUME_SOURCE_MANIFEST_ARTIFACT_NAME": "next",
            # artifact id + digest omitted
        }
        with pytest.raises(ContinuationSourceError, match="RUN_ATTEMPT|ARTIFACT_ID"):
            continuation_inputs_from_env(
                env, repository=_REPO, chain_id=_CHAIN, source_sha=_SOURCE_SHA
            )

    @pytest.mark.parametrize("bad", [0, -1, True])
    def test_nonpositive_rejections(self, bad: int) -> None:
        with pytest.raises(ContinuationSourceError, match="positive integer"):
            _inputs(source_run_attempt=bad)

    @pytest.mark.parametrize("digest", ["nothex", "a" * 64])
    def test_unprefixed_digest_is_rejected(self, digest: str) -> None:
        with pytest.raises(ContinuationSourceError, match="sha256"):
            _inputs(manifest_artifact_digest=digest)


class TestTransportTamperCases:
    def _transport_with(self, inputs: ContinuationDispatchInputs, **patch: Any) -> _FakeTransport:
        transport = _fixture_transport(inputs)
        artifact = dict(transport.artifact(_REPO, inputs.manifest_artifact_id))
        artifact.update(patch)
        return _FakeTransport(artifact=artifact, archive=transport.download(_REPO, 77))

    def test_wrong_artifact_id_rejected(self) -> None:
        inputs = _bound_inputs(_inputs())
        transport = self._transport_with(inputs, id=999)
        with pytest.raises(ContinuationSourceError, match="different artifact id"):
            verify_continuation_source(inputs, transport, current_run_id=501)

    def test_wrong_name_rejected(self) -> None:
        inputs = _bound_inputs(_inputs())
        transport = self._transport_with(inputs, name="other-name")
        with pytest.raises(ContinuationSourceError, match="different artifact name"):
            verify_continuation_source(inputs, transport, current_run_id=501)

    def test_wrong_owner_run_rejected(self) -> None:
        inputs = _bound_inputs(_inputs())
        transport = self._transport_with(inputs, workflow_run={"id": 499})
        with pytest.raises(ContinuationSourceError, match="not owned by the named source run"):
            verify_continuation_source(inputs, transport, current_run_id=501)

    def test_expired_rejected(self) -> None:
        inputs = _bound_inputs(_inputs())
        transport = self._transport_with(inputs, expired=True)
        with pytest.raises(ContinuationSourceError, match="expired"):
            verify_continuation_source(inputs, transport, current_run_id=501)

    def test_digest_drift_rejected(self) -> None:
        inputs = _bound_inputs(_inputs())
        transport = self._transport_with(inputs, digest=f"sha256:{'b' * 64}")
        with pytest.raises(ContinuationSourceError, match="drifted"):
            verify_continuation_source(inputs, transport, current_run_id=501)

    def test_download_size_drift_rejected(self) -> None:
        inputs = _bound_inputs(_inputs())
        transport = _fixture_transport(inputs)
        artifact = dict(transport.artifact(_REPO, 77))
        artifact["size_in_bytes"] = int(artifact["size_in_bytes"]) + 1
        tampered = _FakeTransport(
            artifact=artifact,
            archive=transport.download(_REPO, 77),
            run=transport.workflow_run(_REPO, 500),
        )
        with pytest.raises(ContinuationSourceError, match="size does not match"):
            verify_continuation_source(inputs, tampered, current_run_id=501)

    def test_download_bytes_drift_rejected(self) -> None:
        inputs = _bound_inputs(_inputs())
        transport = _fixture_transport(inputs)
        raw = transport.download(_REPO, 77) + b"x"
        artifact = dict(transport.artifact(_REPO, 77))
        artifact["size_in_bytes"] = len(raw)
        tampered = _FakeTransport(
            artifact=artifact,
            archive=raw,
            run=transport.workflow_run(_REPO, 500),
        )
        with pytest.raises(ContinuationSourceError, match="do not match the dispatch digest"):
            verify_continuation_source(inputs, tampered, current_run_id=501)

    @pytest.mark.parametrize(
        ("field", "value", "match"),
        [
            ("run_attempt", 3, "attempt differs"),
            ("event", "push", "workflow_dispatch"),
            ("head_sha", "2" * 40, "head SHA differs"),
        ],
    )
    def test_owner_run_identity_drift_rejected(self, field: str, value: object, match: str) -> None:
        inputs = _bound_inputs(_inputs())
        transport = _fixture_transport(inputs)
        run = dict(transport.workflow_run(_REPO, 500))
        run[field] = value
        tampered = _FakeTransport(
            artifact=transport.artifact(_REPO, 77),
            archive=transport.download(_REPO, 77),
            run=run,
        )
        with pytest.raises(ContinuationSourceError, match=match):
            verify_continuation_source(inputs, tampered, current_run_id=501)


class TestJoins:
    def test_same_run_rejected(self) -> None:
        inputs = _bound_inputs(_inputs())
        transport = _fixture_transport(inputs)
        with pytest.raises(ContinuationSourceError, match="different run"):
            verify_continuation_source(inputs, transport, current_run_id=500)

    def test_chain_mismatch_rejected(self) -> None:
        inputs = _bound_inputs(_inputs(chain_id="other-chain"))
        transport = _fixture_transport(
            _inputs(chain_id=inputs.chain_id, manifest_artifact_name=inputs.manifest_artifact_name)
        )
        # Rebind name to fixture for the fixture transaction's chain.
        name = f"next-iteration-manifest-{inputs.chain_id}-iter-3"
        bound = replace(inputs, manifest_artifact_name=name)
        bound = _bound_inputs(bound)
        transport = _fixture_transport(bound)
        with pytest.raises(ContinuationSourceError, match="chain"):
            verify_continuation_source(
                replace(bound, chain_id="mismatch-chain"), transport, current_run_id=501
            )

    def test_name_generation_mismatch_rejected(self) -> None:
        inputs = _bound_inputs(
            _inputs(manifest_artifact_name=f"next-iteration-manifest-{_CHAIN}-iter-4")
        )
        transport = _fixture_transport(inputs)
        with pytest.raises(ContinuationSourceError, match="generation does not match"):
            verify_continuation_source(inputs, transport, current_run_id=501)

    def test_member_digest_is_recorded(self) -> None:
        inputs = _bound_inputs(_inputs())
        transport = _fixture_transport(inputs)
        verified = verify_continuation_source(inputs, transport, current_run_id=501)
        member_bytes = None
        with zipfile.ZipFile(io.BytesIO(transport.download(_REPO, 77))) as archive:
            member_bytes = archive.read(_MEMBER)
        assert member_bytes is not None
        assert verified.member.member_sha256 == hashlib.sha256(member_bytes).hexdigest()
        assert verified.member.member_size_bytes == len(member_bytes)


class TestArchiveSafety:
    def test_duplicate_member_rejected(self) -> None:
        inputs = _bound_inputs(_inputs())
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(_MEMBER, b"{}")
            archive.writestr(_MEMBER, b"{}")
        raw = buffer.getvalue()
        transport = _FakeTransport(
            artifact={
                "id": 77,
                "name": inputs.manifest_artifact_name,
                "workflow_run": {"id": 500},
                "digest": f"sha256:{hashlib.sha256(raw).hexdigest()}",
                "size_in_bytes": len(raw),
                "expired": False,
            },
            archive=raw,
        )
        with pytest.raises(ContinuationSourceError, match="duplicate"):
            verify_continuation_source(
                replace(
                    inputs, manifest_artifact_digest=f"sha256:{hashlib.sha256(raw).hexdigest()}"
                ),
                transport,
                current_run_id=501,
            )

    def test_missing_member_rejected(self) -> None:
        inputs = _bound_inputs(_inputs())
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("other/member.json", b"{}")
        raw = buffer.getvalue()
        digest = f"sha256:{hashlib.sha256(raw).hexdigest()}"
        transport = _FakeTransport(
            artifact={
                "id": 77,
                "name": inputs.manifest_artifact_name,
                "workflow_run": {"id": 500},
                "digest": digest,
                "size_in_bytes": len(raw),
                "expired": False,
            },
            archive=raw,
        )
        with pytest.raises(ContinuationSourceError, match="exactly one"):
            verify_continuation_source(
                replace(inputs, manifest_artifact_digest=digest), transport, current_run_id=501
            )

    def test_symlink_member_rejected(self) -> None:
        inputs = _bound_inputs(_inputs())
        buffer = io.BytesIO()
        link = zipfile.ZipInfo(_MEMBER)
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(link, "target.json")
        raw = buffer.getvalue()
        digest = f"sha256:{hashlib.sha256(raw).hexdigest()}"
        transport = _FakeTransport(
            artifact={
                "id": 77,
                "name": inputs.manifest_artifact_name,
                "workflow_run": {"id": 500},
                "digest": digest,
                "size_in_bytes": len(raw),
                "expired": False,
            },
            archive=raw,
        )
        with pytest.raises(ContinuationSourceError, match="regular file"):
            verify_continuation_source(
                replace(inputs, manifest_artifact_digest=digest), transport, current_run_id=501
            )

    def test_file_parent_collision_rejected(self) -> None:
        inputs = _bound_inputs(_inputs())
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("manifests", b"not-a-directory")
            archive.writestr(_MEMBER, b"{}")
        raw = buffer.getvalue()
        digest = f"sha256:{hashlib.sha256(raw).hexdigest()}"
        transport = _FakeTransport(
            artifact={
                "id": 77,
                "name": inputs.manifest_artifact_name,
                "workflow_run": {"id": 500},
                "digest": digest,
                "size_in_bytes": len(raw),
                "expired": False,
            },
            archive=raw,
        )
        with pytest.raises(ContinuationSourceError, match="parent collision"):
            verify_continuation_source(
                replace(inputs, manifest_artifact_digest=digest), transport, current_run_id=501
            )
