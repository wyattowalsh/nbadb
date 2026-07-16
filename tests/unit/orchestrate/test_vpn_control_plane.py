from __future__ import annotations

import hashlib
import inspect
import io
import json
import stat
import types
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.error import URLError

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

MODULE_PATH = Path(__file__).resolve().parents[3] / ".github" / "scripts" / "vpn_control_plane.py"
MODULE_CODE = compile(MODULE_PATH.read_text(encoding="utf-8"), str(MODULE_PATH), "exec")
TEST_SOURCE_SHA = "a" * 40
TEST_WORKFLOW_HEAD_SHA = "b" * 40


def _load_module():
    module = types.ModuleType("github_vpn_control_plane")
    module.__file__ = str(MODULE_PATH)
    exec(MODULE_CODE, module.__dict__)
    return module


@pytest.fixture(scope="module")
def module():
    return _load_module()


class FakeResponse:
    def __init__(
        self,
        payload: object,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.headers = headers or {}
        self.body = (
            payload
            if isinstance(payload, bytes)
            else json.dumps(payload, separators=(",", ":")).encode()
        )
        self.closed = False

    def read(self, _limit: int = -1) -> bytes:
        return self.body

    def close(self) -> None:
        self.closed = True


class FakeOpener:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[object, float]] = []

    def __call__(self, request: object, *, timeout: float) -> FakeResponse:
        self.requests.append((request, timeout))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        assert isinstance(response, FakeResponse)
        return response


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


def _artifact(name: str, *, artifact_id: int = 1, expired: bool = False) -> dict[str, object]:
    return {"id": artifact_id, "name": name, "expired": expired}


def _marker_archive(payload: object, *, filename: str = "auth-circuit-marker.json") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(filename, json.dumps(payload, separators=(",", ":")))
    return buffer.getvalue()


def _marker_artifact(
    name: str,
    archive: bytes,
    *,
    artifact_id: int = 77,
    run_id: int = 15,
    workflow_head_sha: str = TEST_WORKFLOW_HEAD_SHA,
) -> dict[str, object]:
    return {
        "id": artifact_id,
        "name": name,
        "expired": False,
        "size_in_bytes": len(archive),
        "archive_download_url": (
            f"https://api.github.com/repos/owner/repo/actions/artifacts/{artifact_id}/zip"
        ),
        "digest": f"sha256:{hashlib.sha256(archive).hexdigest()}",
        "workflow_run": {"id": run_id, "head_sha": workflow_head_sha},
    }


def test_artifact_names_are_run_attempt_scoped_and_capacity_is_per_lane(module) -> None:
    assert (
        module.auth_circuit_artifact_name("987654", "3")
        == "full-extraction-vpn-auth-circuit-run-987654-attempt-3"
    )
    assert (
        module.capacity_marker_artifact_name(987654, 3, 2)
        == "vpn-capacity-connected-run-987654-attempt-3-lane-2"
    )

    with pytest.raises(module.InputValidationError, match="run ID"):
        module.auth_circuit_artifact_name("invalid", 3)
    with pytest.raises(module.InputValidationError, match="lane index"):
        module.capacity_marker_artifact_name(987654, 3, -1)


def test_list_artifacts_uses_gh_token_version_header_and_paginates(module) -> None:
    first_page = [_artifact(f"other-{index}", artifact_id=index + 1) for index in range(100)]
    target = module.auth_circuit_artifact_name(987654, 3)
    opener = FakeOpener(
        [
            FakeResponse({"total_count": 101, "artifacts": first_page}),
            FakeResponse({"total_count": 101, "artifacts": [_artifact(target, artifact_id=101)]}),
        ]
    )

    artifacts = module.list_workflow_run_artifacts(
        repository="owner/repo",
        run_id="987654",
        env={"GH_TOKEN": "token-value-that-must-not-be-logged"},
        opener=opener,
    )

    assert len(artifacts) == 101
    assert artifacts[-1]["name"] == target
    assert len(opener.requests) == 2
    first_request, timeout = opener.requests[0]
    headers = {key.lower(): value for key, value in first_request.header_items()}
    assert headers["authorization"] == "Bearer token-value-that-must-not-be-logged"
    assert headers["x-github-api-version"] == "2026-03-10"
    assert headers["accept"] == "application/vnd.github+json"
    assert timeout == 15.0
    assert "page=1" in first_request.full_url
    assert "name=" not in first_request.full_url
    assert "page=2" in opener.requests[1][0].full_url


def test_list_artifacts_never_follows_authenticated_redirects(module) -> None:
    default_opener = (
        inspect.signature(module.list_workflow_run_artifacts).parameters["opener"].default
    )
    assert default_opener is module._open_without_redirect

    opener = FakeOpener(
        [
            FakeResponse(
                b"",
                status=302,
                headers={"Location": "https://untrusted.example.test/artifacts"},
            )
        ]
    )
    with pytest.raises(module.GitHubApiError, match="HTTP 302"):
        module.list_workflow_run_artifacts(
            repository="owner/repo",
            run_id=10,
            env={"GH_TOKEN": "secret-token"},
            opener=opener,
        )
    assert len(opener.requests) == 1


@pytest.mark.parametrize(
    "payload,error",
    [
        ([], "JSON object"),
        ({"total_count": "1", "artifacts": []}, "total_count"),
        ({"total_count": 1, "artifacts": {}}, "artifacts must be an array"),
        ({"total_count": 1, "artifacts": ["bad"]}, "entries must be objects"),
        (
            {"total_count": 1, "artifacts": [{"name": "marker"}]},
            "expired flags must be booleans",
        ),
        (
            {"total_count": 1, "artifacts": [{"id": True, "name": "marker", "expired": False}]},
            "ids must be positive integers",
        ),
    ],
)
def test_list_artifacts_rejects_invalid_response_objects(
    module,
    payload: object,
    error: str,
) -> None:
    opener = FakeOpener([FakeResponse(payload)])

    with pytest.raises(module.GitHubApiError, match=error):
        module.list_workflow_run_artifacts(
            repository="owner/repo",
            run_id=10,
            env={"GH_TOKEN": "secret-token"},
            opener=opener,
        )


def test_list_artifacts_retries_transport_failures_with_a_fixed_budget(module) -> None:
    secret = "token-that-must-stay-secret"
    sleeps: list[float] = []
    opener = FakeOpener(
        [
            URLError(f"transport failed near {secret}"),
            URLError(f"transport failed again near {secret}"),
            FakeResponse({"total_count": 0, "artifacts": []}),
        ]
    )

    assert (
        module.list_workflow_run_artifacts(
            repository="owner/repo",
            run_id=10,
            env={"GH_TOKEN": secret},
            attempts=3,
            retry_delay_seconds=0.25,
            opener=opener,
            sleep=sleeps.append,
        )
        == []
    )
    assert len(opener.requests) == 3
    assert sleeps == [0.25, 0.5]

    failing = FakeOpener([URLError(secret), URLError(secret)])
    with pytest.raises(module.GitHubApiError) as exc_info:
        module.list_workflow_run_artifacts(
            repository="owner/repo",
            run_id=10,
            env={"GH_TOKEN": secret},
            attempts=2,
            retry_delay_seconds=0,
            opener=failing,
            sleep=lambda _seconds: None,
        )
    assert secret not in str(exc_info.value)
    assert len(failing.requests) == 2


def test_list_artifacts_retries_explicit_retryable_http_status(module) -> None:
    sleeps: list[float] = []
    opener = FakeOpener(
        [
            FakeResponse({}, status=503),
            FakeResponse({"total_count": 0, "artifacts": []}),
        ]
    )

    assert (
        module.list_workflow_run_artifacts(
            repository="owner/repo",
            run_id=10,
            env={"GH_TOKEN": "secret-token"},
            attempts=2,
            retry_delay_seconds=0.5,
            opener=opener,
            sleep=sleeps.append,
        )
        == []
    )
    assert len(opener.requests) == 2
    assert sleeps == [0.5]


def test_exact_lookup_ignores_expired_and_rejects_live_duplicates(module) -> None:
    name = "vpn-auth-circuit-chain-run-1-attempt-1"
    inventory = [
        _artifact(name, artifact_id=1, expired=True),
        _artifact(name, artifact_id=2),
        _artifact("unrelated", artifact_id=3),
    ]

    assert module.exact_unexpired_artifact(inventory, name)["id"] == 2
    assert module.exact_unexpired_artifact([inventory[0]], name) is None

    with pytest.raises(module.ArtifactAmbiguityError, match="multiple unexpired"):
        module.exact_unexpired_artifact(
            [inventory[1], _artifact(name, artifact_id=4)],
            name,
        )


def test_find_exact_artifact_uses_the_api_name_filter(module) -> None:
    name = module.auth_circuit_artifact_name(15, 2)
    opener = FakeOpener(
        [FakeResponse({"total_count": 1, "artifacts": [_artifact(name, artifact_id=7)]})]
    )

    artifact = module.find_exact_workflow_run_artifact(
        exact_name=name,
        repository="owner/repo",
        run_id=15,
        env={"GH_TOKEN": "secret-token"},
        opener=opener,
    )

    assert artifact is not None
    assert artifact["id"] == 7
    assert len(opener.requests) == 1
    assert f"name={name}" in opener.requests[0][0].full_url


def test_load_auth_marker_artifact_downloads_one_safe_json_file(module) -> None:
    payload = {"schema_version": 1, "source_sha": TEST_SOURCE_SHA}
    archive = _marker_archive(payload)
    name = module.auth_circuit_artifact_name(15, 2)
    api_opener = FakeOpener(
        [
            FakeResponse(
                b"",
                status=302,
                headers={"Location": "https://artifact.example.test/signed-marker"},
            )
        ]
    )
    content_opener = FakeOpener([FakeResponse(archive)])

    loaded = module.load_auth_marker_artifact(
        _marker_artifact(name, archive),
        repository="owner/repo",
        expected_name=name,
        run_id=15,
        workflow_head_sha=TEST_WORKFLOW_HEAD_SHA,
        env={"GH_TOKEN": "secret-token"},
        api_opener=api_opener,
        content_opener=content_opener,
    )

    assert loaded == payload
    request, timeout = api_opener.requests[0]
    assert request.full_url.endswith("/repos/owner/repo/actions/artifacts/77/zip")
    assert timeout == 15.0
    headers = {key.lower(): value for key, value in request.header_items()}
    assert headers["authorization"] == "Bearer secret-token"
    content_request, content_timeout = content_opener.requests[0]
    content_headers = {key.lower(): value for key, value in content_request.header_items()}
    assert content_request.full_url == "https://artifact.example.test/signed-marker"
    assert "authorization" not in content_headers
    assert content_headers["accept"] == "application/zip"
    assert content_timeout == 15.0


def test_auth_commands_expose_separate_workflow_and_source_sha_arguments(module) -> None:
    for command in ("auth-guard", "verify-auth"):
        args = module.build_parser().parse_args(
            [
                command,
                "--source-sha",
                TEST_SOURCE_SHA,
                "--workflow-head-sha",
                TEST_WORKFLOW_HEAD_SHA,
                "--auth-source",
                "configured",
            ]
        )

        assert args.source_sha == TEST_SOURCE_SHA
        assert args.workflow_head_sha == TEST_WORKFLOW_HEAD_SHA
        assert args.auth_source == "configured"


def test_auth_guard_cli_binds_rest_and_marker_provenance_to_different_shas(
    module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "github-output.txt"
    name = module.auth_circuit_artifact_name(15, 2)
    artifact = {"name": name}
    payload = module.build_marker_payload(
        kind="auth-circuit",
        repository="owner/repo",
        chain_id="chain-abc",
        source_sha=TEST_SOURCE_SHA,
        run_id=15,
        run_attempt=2,
        lane_id="historical-14",
        lane_index=14,
        auth_source="configured",
        vpn_status="vpn_auth_failure",
        vpn_server="",
        timestamp="2026-07-16T14:15:16Z",
    )
    observed: dict[str, object] = {}

    def fake_find_exact_workflow_run_artifact(**_kwargs: object) -> dict[str, object]:
        return artifact

    def fake_load_auth_marker_artifact(
        candidate: object,
        **kwargs: object,
    ) -> dict[str, object]:
        observed["artifact"] = candidate
        observed["workflow_head_sha"] = kwargs["workflow_head_sha"]
        return payload

    monkeypatch.setattr(
        module,
        "find_exact_workflow_run_artifact",
        fake_find_exact_workflow_run_artifact,
    )
    monkeypatch.setattr(module, "load_auth_marker_artifact", fake_load_auth_marker_artifact)

    assert (
        module.main(
            ["auth-guard"],
            env={
                "GITHUB_REPOSITORY": "owner/repo",
                "GITHUB_RUN_ID": "15",
                "GITHUB_RUN_ATTEMPT": "2",
                "GITHUB_OUTPUT": str(output),
                "CHAIN_ID": "chain-abc",
                "WORKFLOW_SOURCE_SHA": TEST_SOURCE_SHA,
                "GITHUB_SHA": TEST_WORKFLOW_HEAD_SHA,
                "VPN_AUTH_SOURCE": "configured",
            },
        )
        == 1
    )
    assert observed == {
        "artifact": artifact,
        "workflow_head_sha": TEST_WORKFLOW_HEAD_SHA,
    }
    assert output.read_text(encoding="utf-8") == "status=vpn_auth_circuit_open\n"


@pytest.mark.parametrize(
    "archive,error",
    [
        (b"not-a-zip", "valid ZIP"),
        (_marker_archive({}, filename="../auth-circuit-marker.json"), "path or size"),
        (_marker_archive({}, filename="wrong.json"), "path or size"),
    ],
)
def test_load_auth_marker_artifact_rejects_untrusted_archives(
    module,
    archive: bytes,
    error: str,
) -> None:
    name = module.auth_circuit_artifact_name(15, 2)
    api_opener = FakeOpener(
        [
            FakeResponse(
                b"",
                status=302,
                headers={"Location": "https://artifact.example.test/signed-marker"},
            )
        ]
    )
    content_opener = FakeOpener([FakeResponse(archive)])

    with pytest.raises(module.GitHubApiError, match=error):
        module.load_auth_marker_artifact(
            _marker_artifact(name, archive),
            repository="owner/repo",
            expected_name=name,
            run_id=15,
            workflow_head_sha=TEST_WORKFLOW_HEAD_SHA,
            env={"GH_TOKEN": "secret-token"},
            api_opener=api_opener,
            content_opener=content_opener,
        )


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("name", "wrong", "identity"),
        ("expired", True, "identity"),
        ("size_in_bytes", 0, "size"),
        ("digest", "sha256:" + "0" * 64, "digest does not match"),
        ("digest", None, "digest is missing"),
        ("archive_download_url", "https://example.test/wrong", "download URL"),
        (
            "workflow_run",
            {"id": 16, "head_sha": TEST_WORKFLOW_HEAD_SHA},
            "workflow run",
        ),
        ("workflow_run", {"id": 15, "head_sha": "c" * 40}, "workflow head SHA"),
    ],
)
def test_load_auth_marker_artifact_rejects_unbound_artifact_metadata(
    module,
    field: str,
    value: object,
    error: str,
) -> None:
    archive = _marker_archive({"schema_version": 1})
    name = module.auth_circuit_artifact_name(15, 2)
    artifact = _marker_artifact(name, archive)
    artifact[field] = value
    api_opener = FakeOpener(
        [
            FakeResponse(
                b"",
                status=302,
                headers={"Location": "https://artifact.example.test/signed-marker"},
            )
        ]
    )
    content_opener = FakeOpener([FakeResponse(archive)])

    with pytest.raises(module.GitHubApiError, match=error):
        module.load_auth_marker_artifact(
            artifact,
            repository="owner/repo",
            expected_name=name,
            run_id=15,
            workflow_head_sha=TEST_WORKFLOW_HEAD_SHA,
            env={"GH_TOKEN": "secret-token"},
            api_opener=api_opener,
            content_opener=content_opener,
        )


def test_load_auth_marker_artifact_binds_declared_size_to_downloaded_bytes(module) -> None:
    archive = _marker_archive({"schema_version": 1})
    name = module.auth_circuit_artifact_name(15, 2)
    artifact = _marker_artifact(name, archive)
    artifact["size_in_bytes"] = len(archive) - 1
    api_opener = FakeOpener(
        [
            FakeResponse(
                b"",
                status=302,
                headers={"Location": "https://artifact.example.test/signed-marker"},
            )
        ]
    )

    with pytest.raises(module.GitHubApiError, match="size does not match"):
        module.load_auth_marker_artifact(
            artifact,
            repository="owner/repo",
            expected_name=name,
            run_id=15,
            workflow_head_sha=TEST_WORKFLOW_HEAD_SHA,
            env={"GH_TOKEN": "secret-token"},
            api_opener=api_opener,
            content_opener=FakeOpener([FakeResponse(archive)]),
        )


def test_marker_archive_rejects_extra_entries_and_symlinks(module) -> None:
    extra_buffer = io.BytesIO()
    with zipfile.ZipFile(extra_buffer, "w") as archive:
        archive.writestr("auth-circuit-marker.json", "{}")
        archive.writestr("extra/", b"")
    with pytest.raises(module.GitHubApiError, match="exactly one regular file"):
        module._marker_payload_from_archive(extra_buffer.getvalue())

    symlink_buffer = io.BytesIO()
    with zipfile.ZipFile(symlink_buffer, "w") as archive:
        entry = zipfile.ZipInfo("auth-circuit-marker.json")
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(entry, "target")
    with pytest.raises(module.GitHubApiError, match="path or size"):
        module._marker_payload_from_archive(symlink_buffer.getvalue())


@pytest.mark.parametrize(
    "location",
    [
        "http://artifact.example.test/marker",
        "https://user:pass@artifact.example.test/marker",
        "https://artifact.example.test/marker#fragment",
        "not-a-url",
    ],
)
def test_load_auth_marker_artifact_rejects_unsafe_redirects(
    module,
    location: str,
) -> None:
    archive = _marker_archive({"schema_version": 1})
    name = module.auth_circuit_artifact_name(15, 2)
    api_opener = FakeOpener([FakeResponse(b"", status=302, headers={"Location": location})])

    with pytest.raises(module.GitHubApiError, match="redirect location is invalid"):
        module.load_auth_marker_artifact(
            _marker_artifact(name, archive),
            repository="owner/repo",
            expected_name=name,
            run_id=15,
            workflow_head_sha=TEST_WORKFLOW_HEAD_SHA,
            env={"GH_TOKEN": "secret-token"},
            api_opener=api_opener,
            content_opener=FakeOpener([]),
        )


@pytest.mark.parametrize(
    ("result_factory", "expected_status", "expected_exit"),
    [
        (lambda: None, "closed", 0),
        (lambda: {"name": "marker"}, "vpn_auth_circuit_open", 1),
    ],
)
def test_auth_guard_writes_closed_or_open_status(
    module,
    tmp_path: Path,
    result_factory: Callable[[], object],
    expected_status: str,
    expected_exit: int,
) -> None:
    output = tmp_path / "github-output.txt"

    result = module.auth_guard(
        artifact_name="marker",
        artifact_lookup=lambda _name: result_factory(),
        output_path=output,
        stderr=io.StringIO(),
    )

    assert result == expected_exit
    assert output.read_text(encoding="utf-8") == f"status={expected_status}\n"


def test_auth_guard_api_failure_is_closed_to_execution_and_secret_free(
    module,
    tmp_path: Path,
) -> None:
    output = tmp_path / "github-output.txt"
    stderr = io.StringIO()
    secret = "credential-value"

    def fail(_name: str) -> None:
        raise RuntimeError(secret)

    assert (
        module.auth_guard(
            artifact_name="marker",
            artifact_lookup=fail,
            output_path=output,
            stderr=stderr,
        )
        == 1
    )
    assert output.read_text(encoding="utf-8") == "status=vpn_auth_circuit_check_failed\n"
    assert secret not in stderr.getvalue()
    assert "check failed" in stderr.getvalue().lower()


def test_auth_guard_rejects_an_invalid_exact_name_marker(module, tmp_path: Path) -> None:
    output = tmp_path / "github-output.txt"
    stderr = io.StringIO()

    assert (
        module.auth_guard(
            artifact_name="marker",
            artifact_lookup=lambda _name: {"id": 1, "name": "marker"},
            artifact_validator=lambda _artifact: (_ for _ in ()).throw(
                module.InputValidationError("wrong chain")
            ),
            output_path=output,
            stderr=stderr,
        )
        == 1
    )
    assert output.read_text(encoding="utf-8") == "status=vpn_auth_circuit_check_failed\n"
    assert "validation failed" in stderr.getvalue().lower()


def test_verify_auth_wait_is_bounded_with_injected_clock_and_sleep(module) -> None:
    clock = FakeClock()
    calls: list[str] = []
    responses = [None, None, _artifact("marker")]

    def lookup(name: str):
        calls.append(name)
        return responses.pop(0)

    artifact = module.wait_for_auth_marker(
        run_id=15,
        run_attempt=2,
        artifact_lookup=lookup,
        timeout_seconds=5,
        poll_interval_seconds=2,
        clock=clock.monotonic,
        sleep=clock.sleep,
    )

    expected_name = "full-extraction-vpn-auth-circuit-run-15-attempt-2"
    assert artifact["name"] == "marker"
    assert calls == [expected_name, expected_name, expected_name]
    assert clock.sleeps == [2.0, 2.0]


def test_verify_auth_timeout_never_sleeps_past_deadline(module) -> None:
    clock = FakeClock()
    calls = 0

    def lookup(_name: str) -> None:
        nonlocal calls
        calls += 1
        return None

    with pytest.raises(module.MarkerWaitTimeoutError, match="authentication circuit marker"):
        module.wait_for_auth_marker(
            run_id=15,
            run_attempt=2,
            artifact_lookup=lookup,
            timeout_seconds=5,
            poll_interval_seconds=2,
            clock=clock.monotonic,
            sleep=clock.sleep,
        )

    assert clock.sleeps == [2.0, 2.0, 1.0]
    assert clock.value == 5.0
    assert calls == 4


def test_capacity_wait_requires_every_exact_lane_marker(module) -> None:
    clock = FakeClock()
    marker_zero = module.capacity_marker_artifact_name(15, 2, 0)
    marker_one = module.capacity_marker_artifact_name(15, 2, 1)
    inventories = [
        [],
        [_artifact(marker_zero, artifact_id=10)],
        [_artifact(marker_zero, artifact_id=10), _artifact(marker_one, artifact_id=11)],
    ]

    found = module.wait_for_capacity_markers(
        run_id=15,
        run_attempt=2,
        expected=2,
        artifact_lister=lambda: inventories.pop(0),
        timeout_seconds=3,
        poll_interval_seconds=1,
        clock=clock.monotonic,
        sleep=clock.sleep,
    )

    assert {index: artifact["name"] for index, artifact in found.items()} == {
        0: marker_zero,
        1: marker_one,
    }
    assert clock.sleeps == [1.0, 1.0]


def test_capacity_wait_with_zero_expected_does_not_list_artifacts(module) -> None:
    listed = False

    def artifact_lister() -> list[object]:
        nonlocal listed
        listed = True
        return []

    assert (
        module.wait_for_capacity_markers(
            run_id=15,
            run_attempt=2,
            expected=0,
            artifact_lister=artifact_lister,
        )
        == {}
    )
    assert listed is False


def test_marker_payload_binds_all_coordination_provenance(module) -> None:
    payload = module.build_marker_payload(
        kind="auth-circuit",
        repository="owner/repo",
        chain_id="chain-abc",
        source_sha="A" * 40,
        run_id="987654",
        run_attempt="3",
        lane_id="historical-14",
        lane_index="14",
        auth_source="configured",
        vpn_status="vpn_auth_failure",
        vpn_server="us123.nordvpn.com",
        vpn_exit_ip="203.0.113.7",
        timestamp="2026-07-16T14:15:16+00:00",
    )

    assert payload == {
        "schema_version": 1,
        "kind": "vpn_auth_circuit",
        "repository": "owner/repo",
        "chain_id": "chain-abc",
        "source_sha": "a" * 40,
        "run_id": "987654",
        "run_attempt": 3,
        "lane_id": "historical-14",
        "lane_index": 14,
        "auth_source": "configured",
        "vpn_status": "vpn_auth_failure",
        "vpn_server": "us123.nordvpn.com",
        "vpn_exit_ip": "203.0.113.7",
        "attempted_servers": [],
        "failed_servers": [],
        "created_at": "2026-07-16T14:15:16Z",
    }

    assert (
        module.validate_auth_marker_payload(
            payload,
            repository="owner/repo",
            chain_id="chain-abc",
            source_sha="a" * 40,
            run_id=987654,
            run_attempt=3,
            auth_source="configured",
        )
        == payload
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("chain_id", "other-chain"),
        ("source_sha", "b" * 40),
        ("run_id", "123"),
        ("run_attempt", 4),
        ("auth_source", "token"),
        ("vpn_status", "connected"),
        ("schema_version", 2),
    ],
)
def test_validate_auth_marker_payload_rejects_noncanonical_or_stale_content(
    module,
    field: str,
    value: object,
) -> None:
    payload = module.build_marker_payload(
        kind="auth-circuit",
        repository="owner/repo",
        chain_id="chain-abc",
        source_sha="a" * 40,
        run_id=987654,
        run_attempt=3,
        lane_id="historical-14",
        lane_index=14,
        auth_source="configured",
        vpn_status="vpn_auth_failure",
        vpn_server="",
        timestamp="2026-07-16T14:15:16Z",
    )
    payload[field] = value

    with pytest.raises(module.InputValidationError):
        module.validate_auth_marker_payload(
            payload,
            repository="owner/repo",
            chain_id="chain-abc",
            source_sha="a" * 40,
            run_id=987654,
            run_attempt=3,
            auth_source="configured",
        )


def test_auth_circuit_marker_allows_pre_tunnel_server_and_exit_ip_to_be_empty(module) -> None:
    payload = module.build_marker_payload(
        kind="auth-circuit",
        repository="owner/repo",
        chain_id="chain-abc",
        source_sha="a" * 40,
        run_id="987654",
        run_attempt="3",
        lane_id="historical-14",
        lane_index="14",
        auth_source="configured",
        vpn_status="vpn_auth_failure",
        vpn_server="",
        vpn_exit_ip="",
        timestamp="2026-07-16T14:15:16Z",
    )

    assert payload["vpn_server"] == ""
    assert payload["vpn_exit_ip"] == ""


def test_write_marker_cli_accepts_the_capacity_workflow_environment(
    module,
    tmp_path: Path,
) -> None:
    marker_path = tmp_path / "artifacts" / "vpn-control" / "capacity-marker.json"
    github_output = tmp_path / "github-output.txt"
    env = {
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_RUN_ID": "987654",
        "GITHUB_RUN_ATTEMPT": "3",
        "GITHUB_OUTPUT": str(github_output),
        "MARKER_KIND": "capacity",
        "MARKER_PATH": str(marker_path),
        "CHAIN_ID": "chain-abc",
        "SOURCE_SHA": "a" * 40,
        "LANE_INDEX": "2",
        "VPN_AUTH_SOURCE": "configured",
        "VPN_STATUS": "connected",
        "VPN_SERVER": "us123.nordvpn.com",
        "VPN_EXIT_IP": "203.0.113.7",
        "VPN_ATTEMPTED_SERVERS_JSON": ('["us122.nordvpn.com","us123.nordvpn.com"]'),
        "VPN_FAILED_SERVERS_JSON": '["us122.nordvpn.com"]',
    }

    assert module.main(["write-marker"], env=env) == 0
    payload = json.loads(marker_path.read_text(encoding="utf-8"))
    assert payload["kind"] == "vpn_capacity"
    assert payload["lane_id"] == "capacity-2"
    assert payload["lane_index"] == 2
    assert payload["attempted_servers"] == ["us122.nordvpn.com", "us123.nordvpn.com"]
    assert payload["failed_servers"] == ["us122.nordvpn.com"]
    assert github_output.read_text(encoding="utf-8") == (
        "artifact-name=vpn-capacity-connected-run-987654-attempt-3-lane-2\n"
        f"marker-path={marker_path}\n"
    )


def _write_capacity_marker(
    module,
    root: Path,
    *,
    lane_index: int,
    failed_servers: list[str],
) -> None:
    artifact_name = module.capacity_marker_artifact_name(987654, 3, lane_index)
    marker_path = root / artifact_name / "capacity-marker.json"
    attempted_servers = [*failed_servers, f"us{200 + lane_index}.nordvpn.com"]
    payload = module.build_marker_payload(
        kind="capacity",
        repository="owner/repo",
        chain_id="chain-abc",
        source_sha="a" * 40,
        run_id=987654,
        run_attempt=3,
        lane_id=f"capacity-{lane_index}",
        lane_index=lane_index,
        auth_source="configured",
        vpn_status="connected",
        vpn_server=attempted_servers[-1],
        vpn_exit_ip=f"203.0.113.{lane_index + 7}",
        attempted_servers=attempted_servers,
        failed_servers=failed_servers,
        timestamp="2026-07-16T14:15:16Z",
    )
    module.write_json_atomically(marker_path, payload)


def test_aggregate_quarantine_validates_capacity_markers_and_merges_failures(
    module,
    tmp_path: Path,
) -> None:
    marker_root = tmp_path / "capacity-markers"
    _write_capacity_marker(
        module,
        marker_root,
        lane_index=0,
        failed_servers=["us120.nordvpn.com"],
    )
    _write_capacity_marker(
        module,
        marker_root,
        lane_index=1,
        failed_servers=["us121.nordvpn.com", "us120.nordvpn.com"],
    )

    report = module.aggregate_vpn_quarantine(
        marker_directory=marker_root,
        expected_capacity=2,
        repository="owner/repo",
        chain_id="chain-abc",
        source_sha="a" * 40,
        run_id=987654,
        run_attempt=3,
        baseline_servers=["us118.nordvpn.com"],
        discovery_failed_servers=["us119.nordvpn.com", "us118.nordvpn.com"],
    )

    assert report["capacity_marker_count"] == 2
    assert report["vpn_quarantined_servers"] == [
        "us118.nordvpn.com",
        "us119.nordvpn.com",
        "us120.nordvpn.com",
        "us121.nordvpn.com",
    ]


def test_aggregate_quarantine_rejects_missing_or_mismatched_capacity_markers(
    module,
    tmp_path: Path,
) -> None:
    marker_root = tmp_path / "capacity-markers"
    _write_capacity_marker(module, marker_root, lane_index=0, failed_servers=[])

    arguments = {
        "marker_directory": marker_root,
        "expected_capacity": 2,
        "repository": "owner/repo",
        "chain_id": "chain-abc",
        "source_sha": "a" * 40,
        "run_id": 987654,
        "run_attempt": 3,
        "baseline_servers": [],
        "discovery_failed_servers": [],
    }
    with pytest.raises(module.InputValidationError, match="expected 2"):
        module.aggregate_vpn_quarantine(**arguments)

    second_root = tmp_path / "mismatched"
    _write_capacity_marker(module, second_root, lane_index=0, failed_servers=[])
    marker_path = next(second_root.rglob("capacity-marker.json"))
    payload = json.loads(marker_path.read_text(encoding="utf-8"))
    payload["chain_id"] = "other-chain"
    module.write_json_atomically(marker_path, payload)
    arguments["marker_directory"] = second_root
    arguments["expected_capacity"] = 1
    with pytest.raises(module.InputValidationError, match="chain_id"):
        module.aggregate_vpn_quarantine(**arguments)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("schema_version", True, "schema version"),
        ("lane_index", "0", "not canonical"),
    ],
)
def test_aggregate_quarantine_rejects_coercible_noncanonical_capacity_markers(
    module,
    tmp_path: Path,
    field: str,
    value: object,
    error: str,
) -> None:
    marker_root = tmp_path / field
    _write_capacity_marker(module, marker_root, lane_index=0, failed_servers=[])
    marker_path = next(marker_root.rglob("capacity-marker.json"))
    payload = json.loads(marker_path.read_text(encoding="utf-8"))
    payload[field] = value
    module.write_json_atomically(marker_path, payload)

    with pytest.raises(module.InputValidationError, match=error):
        module.aggregate_vpn_quarantine(
            marker_directory=marker_root,
            expected_capacity=1,
            repository="owner/repo",
            chain_id="chain-abc",
            source_sha=TEST_SOURCE_SHA,
            run_id=987654,
            run_attempt=3,
            baseline_servers=[],
            discovery_failed_servers=[],
        )


def test_aggregate_quarantine_cli_writes_report_and_compact_output(
    module,
    tmp_path: Path,
) -> None:
    marker_root = tmp_path / "capacity-markers"
    _write_capacity_marker(
        module,
        marker_root,
        lane_index=0,
        failed_servers=["us122.nordvpn.com"],
    )
    report_path = tmp_path / "effective-quarantine.json"
    github_output = tmp_path / "github-output.txt"
    env = {
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_RUN_ID": "987654",
        "GITHUB_RUN_ATTEMPT": "3",
        "GITHUB_OUTPUT": str(github_output),
        "CHAIN_ID": "chain-abc",
        "SOURCE_SHA": "a" * 40,
        "EXPECTED_CAPACITY": "1",
        "VPN_CAPACITY_MARKER_DIRECTORY": str(marker_root),
        "VPN_QUARANTINE_REPORT_PATH": str(report_path),
        "BASELINE_QUARANTINE_JSON": '["us120.nordvpn.com"]',
        "DISCOVERY_FAILED_SERVERS_JSON": '["us121.nordvpn.com"]',
    }

    assert module.main(["aggregate-quarantine"], env=env) == 0
    assert json.loads(report_path.read_text(encoding="utf-8"))["vpn_quarantined_servers"] == [
        "us120.nordvpn.com",
        "us121.nordvpn.com",
        "us122.nordvpn.com",
    ]
    assert github_output.read_text(encoding="utf-8") == (
        'vpn-quarantined-servers-json=["us120.nordvpn.com",'
        '"us121.nordvpn.com","us122.nordvpn.com"]\n'
    )


def test_atomic_marker_write_is_canonical_and_leaves_no_temporary_file(
    module,
    tmp_path: Path,
) -> None:
    output = tmp_path / "nested" / "marker.json"
    module.write_json_atomically(output, {"z": 1, "a": {"b": True}})

    assert output.read_text(encoding="utf-8") == '{"a":{"b":true},"z":1}\n'
    assert list(output.parent.iterdir()) == [output]


def _deferred_env() -> dict[str, str]:
    return {
        "CHAIN_ID": "chain-abc",
        "ITERATION": "4",
        "LANE_ID": "historical-date-14",
        "LANE_INDEX": "14",
        "NAME": "Historical date lane",
        "KIND": "historical",
        "SOURCE_REF": "main",
        "SOURCE_SHA": "a" * 40,
        "COVERAGE_UNITS_HASH": "b" * 64,
        "CACHE_HIT": "false",
        "RESTORE_SOURCE": "artifact",
        "RESTORE_USABLE": "true",
        "RESTART_MODE": "resume",
        "RESTORE_ERROR": "",
        "RESUME_ONLY": "false",
        "TIMEOUT_SECONDS": "7200",
        "EFFECTIVE_TIMEOUT_SECONDS": "6900",
        "STARTED_AT": "2026-07-16T14:00:00Z",
        "FINISHED_AT": "2026-07-16T14:15:16Z",
        "NETWORK_MODE": "vpn",
        "EFFECTIVE_NETWORK_MODE": "vpn",
        "PATTERNS": "date,game",
        "SEASON_TYPES": "Regular Season,Playoffs",
        "ENDPOINTS": "scoreboard_v2,box_score_summary",
        "CONTEXT_MEASURES": "PTS,AST",
        "SEASON_START": "1962",
        "SEASON_END": "1965",
        "PARENT_LANE_ID": "historical-date-parent",
        "SPLIT_GENERATION": "2",
        "VPN_AUTH_SOURCE": "configured",
        "VPN_SERVER": "us123.nordvpn.com",
        "VPN_INTERFACE": "tun0",
        "VPN_EXIT_IP": "203.0.113.7",
        "VPN_ATTEMPTED_SERVERS_JSON": '["us123.nordvpn.com"]',
        "VPN_FAILED_SERVERS_JSON": '["us122.nordvpn.com"]',
    }


def test_deferred_metadata_is_schema_v3_zero_progress_and_preserves_lane_scope(module) -> None:
    payload = module.build_deferred_metadata(_deferred_env())

    assert payload["metadata_schema_version"] == 3
    assert payload["chain_id"] == "chain-abc"
    assert payload["iteration"] == "4"
    assert payload["lane_id"] == "historical-date-14"
    assert payload["lane_index"] == "14"
    assert payload["lane_name"] == "Historical date lane"
    assert payload["lane_kind"] == "historical"
    assert payload["source_ref"] == "main"
    assert payload["source_sha"] == "a" * 40
    assert payload["coverage_units_hash"] == "b" * 64
    assert payload["patterns"] == ["date", "game"]
    assert payload["season_types"] == ["Regular Season", "Playoffs"]
    assert payload["endpoints"] == ["scoreboard_v2", "box_score_summary"]
    assert payload["context_measures"] == ["PTS", "AST"]
    assert payload["season_start"] == "1962"
    assert payload["season_end"] == "1965"
    assert payload["parent_lane_id"] == "historical-date-parent"
    assert payload["split_generation"] == 2
    assert payload["restore_source"] == "artifact"
    assert payload["restore_usable"] is True
    assert payload["restart_mode"] == "resume"

    assert payload["status"] == "needs_resume"
    assert payload["raw_status"] == "vpn_auth_circuit_open"
    assert payload["failure_class"] == "vpn_circuit_deferred"
    assert payload["failure_class_counts"] == {"vpn_circuit_deferred": 1}
    assert payload["progress"]["completed_calls"] == 0
    assert payload["progress"]["rows_persisted"] == 0
    assert payload["telemetry"]["completed_calls"] == 0
    assert payload["telemetry"]["rows_persisted"] == 0
    assert payload["state_artifact"]["required"] is False
    assert payload["state_artifact"]["attested"] is False
    assert payload["state_artifact"]["uploaded"] is False
    assert payload["vpn"] == {
        "status": "vpn_auth_circuit_open",
        "auth_source": "configured",
        "server": "us123.nordvpn.com",
        "interface": "tun0",
        "exit_ip": "203.0.113.7",
        "attempted_servers": ["us123.nordvpn.com"],
        "failed_servers": ["us122.nordvpn.com"],
    }


def test_write_deferred_metadata_cli_writes_atomic_json_and_outputs(
    module,
    tmp_path: Path,
) -> None:
    env = _deferred_env()
    output = tmp_path / "artifacts" / "extraction" / "lane-metadata.json"
    github_output = tmp_path / "github-output.txt"
    env["GITHUB_OUTPUT"] = str(github_output)

    assert (
        module.main(
            ["write-deferred-metadata", "--output", str(output)],
            env=env,
        )
        == 0
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["raw_status"] == "vpn_auth_circuit_open"
    assert github_output.read_text(encoding="utf-8") == (
        "final-outcome=needs_resume\nsnapshot-attested=false\n"
    )


def test_deferred_metadata_preserves_fail_closed_circuit_check_status(module) -> None:
    env = _deferred_env()
    env["VPN_AUTH_CIRCUIT_STATUS"] = "vpn_auth_circuit_check_failed"

    payload = module.build_deferred_metadata(env)

    assert payload["raw_status"] == "vpn_auth_circuit_check_failed"
    assert payload["failure_class"] == "runner_infrastructure"
    assert payload["failure_class_counts"] == {"runner_infrastructure": 1}
    assert payload["telemetry"]["zero_row_reason"] == "vpn_auth_circuit_check_failed"
    assert payload["vpn_status"] == "vpn_auth_circuit_check_failed"
    assert payload["vpn"]["status"] == "vpn_auth_circuit_check_failed"


def test_deferred_metadata_rejects_missing_or_invalid_provenance(module) -> None:
    missing_hash = _deferred_env()
    del missing_hash["COVERAGE_UNITS_HASH"]
    with pytest.raises(module.InputValidationError, match="COVERAGE_UNITS_HASH"):
        module.build_deferred_metadata(missing_hash)

    invalid_boolean = _deferred_env()
    invalid_boolean["RESTORE_USABLE"] = "yes"
    with pytest.raises(module.InputValidationError, match="true or false"):
        module.build_deferred_metadata(invalid_boolean)
