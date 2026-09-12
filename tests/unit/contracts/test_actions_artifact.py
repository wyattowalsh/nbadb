from __future__ import annotations

import pytest

from nbadb.contracts.actions_artifact import (
    ACTIONS_ARTIFACT_SCHEMA_VERSION,
    ActionsArtifactError,
    ActionsArtifactIdentityV1,
    ArtifactMemberIdentityV1,
    parse_run_attempt_from_artifact_name,
)

_SHA = "a" * 64
_OTHER_SHA = "b" * 64


def _artifact(**overrides: object) -> ActionsArtifactIdentityV1:
    values: dict[str, object] = {
        "repository": "wyattowalsh/nbadb",
        "run_id": 101,
        "run_attempt": 1,
        "artifact_id": 9001,
        "artifact_name": "checkpoint-101-2",
        "artifact_digest": f"sha256:{_SHA}",
        "artifact_size_bytes": 4096,
    }
    values.update(overrides)
    return ActionsArtifactIdentityV1(**values)  # type: ignore[arg-type]


def _member(**overrides: object) -> ArtifactMemberIdentityV1:
    values: dict[str, object] = {
        "artifact": _artifact(),
        "member_path": "evidence/manifest.json",
        "member_sha256": _OTHER_SHA,
        "member_size_bytes": 512,
    }
    values.update(overrides)
    return ArtifactMemberIdentityV1(**values)  # type: ignore[arg-type]


class TestArtifactIdentityValidation:
    def test_valid_identity_round_trips(self) -> None:
        artifact = _artifact()
        parsed = ActionsArtifactIdentityV1.from_payload(artifact.to_payload())
        assert parsed == artifact
        assert parsed.canonical_bytes() == artifact.canonical_bytes()

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("run_id", 0),
            ("run_id", -1),
            ("run_attempt", 0),
            ("run_attempt", -3),
            ("artifact_id", 0),
            ("artifact_size_bytes", 0),
            ("run_id", True),
        ],
    )
    def test_rejects_non_positive_integers(self, field: str, value: object) -> None:
        with pytest.raises(ActionsArtifactError, match="positive integer"):
            _artifact(**{field: value})

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("repository", "not-a-slash-path"),
            ("repository", ""),
            ("artifact_name", ""),
            ("artifact_digest", _SHA),
            ("artifact_digest", f"sha256:{'A' * 64}"),
            ("artifact_digest", f"sha256:{'g' * 64}"),
            ("artifact_digest", f"sha256:{_SHA[:63]}"),
        ],
    )
    def test_rejects_bad_text_forms(self, field: str, value: object) -> None:
        with pytest.raises(ActionsArtifactError):
            _artifact(**{field: value})


class TestArtifactIdentitySerialization:
    def test_rejects_missing_key(self) -> None:
        payload = _artifact().to_payload()
        del payload["run_attempt"]
        with pytest.raises(ActionsArtifactError, match="missing"):
            ActionsArtifactIdentityV1.from_payload(payload)

    def test_rejects_extra_key(self) -> None:
        payload = _artifact().to_payload()
        payload["inferred_attempt"] = 2
        with pytest.raises(ActionsArtifactError, match="extra"):
            ActionsArtifactIdentityV1.from_payload(payload)

    def test_rejects_wrong_schema_version(self) -> None:
        payload = _artifact().to_payload()
        payload["schema_version"] = ACTIONS_ARTIFACT_SCHEMA_VERSION + 1
        with pytest.raises(ActionsArtifactError, match="schema version"):
            ActionsArtifactIdentityV1.from_payload(payload)

    def test_canonical_bytes_deterministic(self) -> None:
        assert _artifact().canonical_bytes() == _artifact().canonical_bytes()
        other = _artifact(run_attempt=2)
        assert other.canonical_bytes() != _artifact().canonical_bytes()


class TestRequireAttempt:
    def test_accepts_exact_owner(self) -> None:
        _artifact().require_attempt(run_id=101, run_attempt=1)

    def test_rejects_wrong_attempt(self) -> None:
        with pytest.raises(ActionsArtifactError, match="owner mismatch"):
            _artifact().require_attempt(run_id=101, run_attempt=2)

    def test_rejects_wrong_run(self) -> None:
        with pytest.raises(ActionsArtifactError, match="owner mismatch"):
            _artifact().require_attempt(run_id=102, run_attempt=1)

    def test_attempt_is_never_inferred_from_artifact_name(self) -> None:
        # The artifact name carries "-2" while the true attempt is 1; every
        # authority path must take attempt from runtime/API evidence, and the
        # only name-based helper deliberately refuses to exist.
        artifact = _artifact(artifact_name="checkpoint-101-2", run_attempt=1)
        with pytest.raises(ActionsArtifactError, match="never be inferred"):
            parse_run_attempt_from_artifact_name(artifact.artifact_name)


class TestMemberIdentity:
    def test_valid_member_round_trips(self) -> None:
        member = _member()
        parsed = ArtifactMemberIdentityV1.from_payload(member.to_payload())
        assert parsed == member
        assert parsed.canonical_bytes() == member.canonical_bytes()

    def test_requires_artifact_identity_type(self) -> None:
        with pytest.raises(ActionsArtifactError, match="ActionsArtifactIdentityV1"):
            _member(artifact={"repository": "a/b"})

    @pytest.mark.parametrize(
        "path",
        [
            "/absolute/path.json",
            "relative\\windows.json",
            "../escape.json",
            "a/../../escape.json",
            "./dot.json",
            "a//double.json",
            "a/./b.json",
            "a/../b.json",
            "",
        ],
    )
    def test_rejects_non_canonical_paths(self, path: str) -> None:
        with pytest.raises(ActionsArtifactError):
            _member(member_path=path)

    def test_rejects_repeated_segment_path(self) -> None:
        with pytest.raises(ActionsArtifactError, match="repeat"):
            _member(member_path="same/same/file.json")

    def test_rejects_bad_member_digest(self) -> None:
        with pytest.raises(ActionsArtifactError, match="member_sha256"):
            _member(member_sha256="B" * 64)
        with pytest.raises(ActionsArtifactError, match="member_sha256"):
            _member(member_sha256=f"sha256:{_OTHER_SHA}")

    def test_rejects_non_positive_member_size(self) -> None:
        with pytest.raises(ActionsArtifactError, match="positive integer"):
            _member(member_size_bytes=0)

    def test_rejects_missing_member_key(self) -> None:
        payload = _member().to_payload()
        del payload["member_path"]
        with pytest.raises(ActionsArtifactError, match="missing"):
            ArtifactMemberIdentityV1.from_payload(payload)

    def test_rejects_extra_member_key(self) -> None:
        payload = _member().to_payload()
        payload["symlink_target"] = "/etc/passwd"
        with pytest.raises(ActionsArtifactError, match="extra"):
            ArtifactMemberIdentityV1.from_payload(payload)
