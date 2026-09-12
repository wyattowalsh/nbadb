"""Focused tests for the dormant public raw-request Actions identity seam."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest

from nbadb.cli.commands._helpers import (
    RawRequestExecutionEnvironmentError,
    _build_settings,
    _raw_request_assurance_authority_from_env,
    _raw_request_execution_identity_from_env,
    _run_pipeline,
)
from nbadb.cli.tui import NbaDbDashboard
from nbadb.orchestrate.orchestrator import PipelineResult
from nbadb.orchestrate.raw_request_context import RawRequestExecutionIdentityV1
from nbadb.orchestrate.w2_runtime_environment import W2RuntimeEnvironmentError
from nbadb.orchestrate.w2_source_call_preparation import (
    W2SourceCallPreparationRuntime,
)
from tests.unit.orchestrate._raw_request_test_support import (
    raw_request_assurance_authority,
)

_SOURCE_SHA = "a" * 40
_OPT_IN = "NBADB_ENABLE_RAW_REQUEST_AUTHORITY"


def _actions_env(*, opt_in: str = "true") -> dict[str, str]:
    return {
        _OPT_IN: opt_in,
        "GITHUB_ACTIONS": "true",
        "WORKFLOW_SOURCE_SHA": _SOURCE_SHA,
        "GITHUB_RUN_ID": "123456",
        "GITHUB_RUN_ATTEMPT": "2",
        "ACTIVE_CHAIN_ID": "chain-2026.08.27",
        "LANE_ID": "stats_lane:7",
    }


def _result() -> PipelineResult:
    return PipelineResult(
        tables_updated=1,
        rows_total=1,
        duration_seconds=0.01,
    )


def _w2_runtime() -> W2SourceCallPreparationRuntime:
    return object.__new__(W2SourceCallPreparationRuntime)


@pytest.mark.parametrize("opt_in", [None, "0", "false"])
def test_raw_request_execution_identity_is_dormant_by_default_and_exact_false(
    opt_in: str | None,
) -> None:
    environ = _actions_env()
    if opt_in is None:
        environ.pop(_OPT_IN)
    else:
        environ[_OPT_IN] = opt_in

    assert _raw_request_execution_identity_from_env(environ) is None


@pytest.mark.parametrize("opt_in", ["1", "true"])
def test_raw_request_execution_identity_accepts_exact_true_lexicals(opt_in: str) -> None:
    identity = _raw_request_execution_identity_from_env(_actions_env(opt_in=opt_in))

    assert type(identity) is RawRequestExecutionIdentityV1
    assert identity.to_dict() == {
        "chain_id": "chain-2026.08.27",
        "lane_id": "stats_lane:7",
        "run_attempt": 2,
        "run_id": 123456,
        "source_sha": _SOURCE_SHA,
    }


@pytest.mark.parametrize(
    "opt_in",
    ["", "TRUE", "False", "yes", "no", "on", "off", " true ", "00", "2"],
)
def test_raw_request_execution_identity_rejects_noncanonical_flag_values(
    opt_in: str,
) -> None:
    with pytest.raises(
        RawRequestExecutionEnvironmentError,
        match="exact boolean lexical value",
    ):
        _raw_request_execution_identity_from_env(_actions_env(opt_in=opt_in))


@pytest.mark.parametrize("actions_value", [None, "", "0", "1", "false", "TRUE"])
def test_enabled_raw_request_identity_rejects_non_actions_execution(
    actions_value: str | None,
) -> None:
    environ = _actions_env()
    if actions_value is None:
        environ.pop("GITHUB_ACTIONS")
    else:
        environ["GITHUB_ACTIONS"] = actions_value

    with pytest.raises(
        RawRequestExecutionEnvironmentError,
        match="exact GitHub Actions execution",
    ):
        _raw_request_execution_identity_from_env(environ)


@pytest.mark.parametrize(
    "missing_name",
    [
        "WORKFLOW_SOURCE_SHA",
        "GITHUB_RUN_ID",
        "GITHUB_RUN_ATTEMPT",
        "ACTIVE_CHAIN_ID",
        "LANE_ID",
    ],
)
def test_enabled_raw_request_identity_rejects_partial_execution(
    missing_name: str,
) -> None:
    environ = _actions_env()
    environ.pop(missing_name)

    with pytest.raises(
        RawRequestExecutionEnvironmentError,
        match="execution provenance is incomplete",
    ):
        _raw_request_execution_identity_from_env(environ)


@pytest.mark.parametrize(
    ("name", "invalid_value", "message"),
    [
        ("WORKFLOW_SOURCE_SHA", "A" * 40, "execution provenance is invalid"),
        ("WORKFLOW_SOURCE_SHA", "a" * 39, "execution provenance is invalid"),
        ("WORKFLOW_SOURCE_SHA", "g" * 40, "execution provenance is invalid"),
        ("GITHUB_RUN_ID", "0", "run ID must be a canonical positive integer"),
        ("GITHUB_RUN_ID", "01", "run ID must be a canonical positive integer"),
        ("GITHUB_RUN_ID", "+1", "run ID must be a canonical positive integer"),
        ("GITHUB_RUN_ID", "-1", "run ID must be a canonical positive integer"),
        ("GITHUB_RUN_ID", "1.0", "run ID must be a canonical positive integer"),
        ("GITHUB_RUN_ID", "\u0661", "run ID must be a canonical positive integer"),
        ("GITHUB_RUN_ATTEMPT", "0", "run attempt must be a canonical positive integer"),
        ("GITHUB_RUN_ATTEMPT", "01", "run attempt must be a canonical positive integer"),
        ("ACTIVE_CHAIN_ID", "token-secret", "execution provenance is invalid"),
        ("LANE_ID", "lane/escape", "execution provenance is invalid"),
    ],
)
def test_enabled_raw_request_identity_rejects_invalid_execution_fields(
    name: str,
    invalid_value: str,
    message: str,
) -> None:
    environ = _actions_env()
    environ[name] = invalid_value

    with pytest.raises(RawRequestExecutionEnvironmentError, match=message):
        _raw_request_execution_identity_from_env(environ)


class _RecordingEnvironment(Mapping[str, str]):
    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = dict(values)
        self.requested: list[str] = []

    def __getitem__(self, key: str) -> str:
        self.requested.append(key)
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        raise AssertionError("the identity seam must not enumerate the environment")

    def __len__(self) -> int:
        raise AssertionError("the identity seam must not inspect environment size")


def test_raw_request_identity_reads_only_public_allowlisted_environment() -> None:
    secret = "must-not-be-captured"
    environ = _RecordingEnvironment(
        {
            **_actions_env(),
            "GH_TOKEN": secret,
            "NORDVPN_TOKEN": secret,
            "SOME_PRIVATE_HEADER": secret,
        }
    )

    identity = _raw_request_execution_identity_from_env(environ)

    assert identity is not None
    assert set(environ.requested) == {
        _OPT_IN,
        "GITHUB_ACTIONS",
        "WORKFLOW_SOURCE_SHA",
        "GITHUB_RUN_ID",
        "GITHUB_RUN_ATTEMPT",
        "ACTIVE_CHAIN_ID",
        "LANE_ID",
    }
    assert secret not in repr(identity)
    assert secret not in repr(identity.to_dict())
    assert set(identity.to_dict()) == {
        "chain_id",
        "lane_id",
        "run_attempt",
        "run_id",
        "source_sha",
    }


def test_raw_request_assurance_is_dormant_without_execution_identity() -> None:
    assert _raw_request_assurance_authority_from_env(None, {}) is None


def test_raw_request_assurance_requires_exact_absolute_regular_roots() -> None:
    identity = _raw_request_execution_identity_from_env(_actions_env())
    assert identity is not None

    with pytest.raises(
        RawRequestExecutionEnvironmentError,
        match="assurance provenance is incomplete",
    ):
        _raw_request_assurance_authority_from_env(identity, {})


def test_raw_request_assurance_revalidates_generation_and_source(
    tmp_path: Path,
) -> None:
    identity = _raw_request_execution_identity_from_env(_actions_env())
    assert identity is not None
    generation = tmp_path / "generation"
    upstream = tmp_path / "nba-api"
    generation.mkdir()
    upstream.mkdir()
    authority = raw_request_assurance_authority(source_sha=identity.source_sha)
    environ = {
        "NBADB_RAW_REQUEST_ASSURANCE_GENERATION": str(generation),
        "ENDPOINT_ANALYSIS_DOCS_ROOT": str(upstream),
    }

    with patch(
        "nbadb.orchestrate.raw_request_assurance.load_raw_request_assurance_authority",
        return_value=authority,
    ) as load:
        observed = _raw_request_assurance_authority_from_env(identity, environ)

    assert observed is authority
    load.assert_called_once_with(
        generation,
        project_root=Path.cwd(),
        endpoint_analysis_docs_root=upstream,
    )


def test_non_tui_pipeline_passes_exact_identity_to_orchestrator() -> None:
    result = _result()
    assurance_authority = raw_request_assurance_authority(source_sha=_SOURCE_SHA)
    w2_runtime = _w2_runtime()
    observed_kwargs: dict[str, object] = {}

    class FakeOrchestrator:
        def __init__(self, **kwargs: object) -> None:
            observed_kwargs.update(kwargs)

    async def run_pipeline(_orchestrator: object) -> PipelineResult:
        return result

    with (
        patch.dict("os.environ", _actions_env(), clear=True),
        patch(
            "nbadb.cli.commands._helpers._raw_request_assurance_authority_from_env",
            return_value=assurance_authority,
        ),
        patch(
            "nbadb.orchestrate.w2_runtime_environment.w2_source_call_preparation_runtime_from_env",
            return_value=w2_runtime,
        ) as build_w2_runtime,
        patch("nbadb.cli.commands._helpers.sys.stdout") as stdout,
        patch("nbadb.cli.commands._helpers._setup_logging"),
        patch("nbadb.cli.commands._helpers._print_result"),
    ):
        stdout.isatty.return_value = False
        _run_pipeline(
            "backfill",
            run_pipeline,
            _build_settings(),
            verbose=True,
            orchestrator_cls=FakeOrchestrator,
        )

    identity = observed_kwargs.get("raw_request_execution_identity")
    assert type(identity) is RawRequestExecutionIdentityV1
    assert identity.source_sha == _SOURCE_SHA
    assert observed_kwargs["raw_request_assurance_authority"] is assurance_authority
    assert observed_kwargs["w2_preparation_runtime"] is w2_runtime
    assert build_w2_runtime.call_args.args == (identity, assurance_authority)
    assert set(observed_kwargs) == {
        "progress",
        "raw_request_assurance_authority",
        "raw_request_execution_identity",
        "settings",
        "w2_preparation_runtime",
    }


@pytest.mark.parametrize("opt_in", [None, "0", "false"])
def test_non_tui_default_constructor_remains_backward_compatible(
    opt_in: str | None,
) -> None:
    result = _result()
    constructed = False

    class LegacyOrchestrator:
        def __init__(self, *, settings: object, progress: object) -> None:
            nonlocal constructed
            constructed = settings is not None and progress is not None

    async def run_pipeline(_orchestrator: object) -> PipelineResult:
        return result

    environ = _actions_env()
    if opt_in is None:
        environ.pop(_OPT_IN)
    else:
        environ[_OPT_IN] = opt_in
    with (
        patch.dict("os.environ", environ, clear=True),
        patch(
            "nbadb.orchestrate.w2_runtime_environment.w2_source_call_preparation_runtime_from_env",
            return_value=None,
        ) as build_w2_runtime,
        patch("nbadb.cli.commands._helpers.sys.stdout") as stdout,
        patch("nbadb.cli.commands._helpers._setup_logging"),
        patch("nbadb.cli.commands._helpers._print_result"),
    ):
        stdout.isatty.return_value = False
        _run_pipeline(
            "backfill",
            run_pipeline,
            _build_settings(),
            verbose=True,
            orchestrator_cls=LegacyOrchestrator,
        )

    assert constructed
    build_w2_runtime.assert_called_once_with(None, None)


def test_tui_pipeline_forwards_exact_identity_to_dashboard_entrypoint() -> None:
    result = _result()
    assurance_authority = raw_request_assurance_authority(source_sha=_SOURCE_SHA)
    w2_runtime = _w2_runtime()

    async def run_pipeline(_orchestrator: object) -> PipelineResult:
        return result

    with (
        patch.dict("os.environ", _actions_env(), clear=True),
        patch(
            "nbadb.cli.commands._helpers._raw_request_assurance_authority_from_env",
            return_value=assurance_authority,
        ),
        patch(
            "nbadb.orchestrate.w2_runtime_environment.w2_source_call_preparation_runtime_from_env",
            return_value=w2_runtime,
        ) as build_w2_runtime,
        patch("nbadb.cli.commands._helpers.sys.stdout") as stdout,
        patch(
            "nbadb.cli.tui.run_with_tui",
            return_value=(result, None, None),
        ) as run_with_tui,
        patch("nbadb.cli.commands._helpers._print_result"),
    ):
        stdout.isatty.return_value = True
        _run_pipeline(
            "backfill",
            run_pipeline,
            _build_settings(),
            verbose=False,
            orchestrator_cls=type("FakeOrchestrator", (), {}),
        )

    identity = run_with_tui.call_args.kwargs["raw_request_execution_identity"]
    assert type(identity) is RawRequestExecutionIdentityV1
    assert identity.to_dict()["lane_id"] == "stats_lane:7"
    assert run_with_tui.call_args.kwargs["raw_request_assurance_authority"] is assurance_authority
    assert run_with_tui.call_args.kwargs["w2_preparation_runtime"] is w2_runtime
    assert build_w2_runtime.call_args.args == (identity, assurance_authority)


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_tui_constructs_orchestrator_with_only_opted_in_identity(
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool,
) -> None:
    identity = _raw_request_execution_identity_from_env(_actions_env()) if enabled else None
    assurance_authority = (
        raw_request_assurance_authority(source_sha=_SOURCE_SHA) if enabled else None
    )
    w2_runtime = _w2_runtime() if enabled else None
    observed_kwargs: dict[str, object] = {}
    result = _result()

    if enabled:

        class FakeOrchestrator:
            def __init__(self, **kwargs: object) -> None:
                observed_kwargs.update(kwargs)

            def close(self) -> None:
                return None

    else:

        class FakeOrchestrator:
            def __init__(self, *, settings: object, progress: object) -> None:
                observed_kwargs.update(settings=settings, progress=progress)

            def close(self) -> None:
                return None

    async def run_pipeline(_orchestrator: object) -> PipelineResult:
        return result

    app = NbaDbDashboard(
        mode="backfill",
        run_fn=run_pipeline,
        settings={"data": "settings"},
        orchestrator_cls=FakeOrchestrator,
        raw_request_execution_identity=identity,
        raw_request_assurance_authority=assurance_authority,
        w2_preparation_runtime=w2_runtime,
    )
    monkeypatch.setattr(app, "write_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app, "set_timer", lambda *_args, **_kwargs: None)

    launch = cast("Any", NbaDbDashboard._launch_pipeline).__wrapped__
    await launch(app)

    expected_keys = {"progress", "settings"}
    if enabled:
        expected_keys.add("raw_request_execution_identity")
        expected_keys.add("raw_request_assurance_authority")
        expected_keys.add("w2_preparation_runtime")
        assert observed_kwargs["raw_request_execution_identity"] is identity
        assert observed_kwargs["raw_request_assurance_authority"] is assurance_authority
        assert observed_kwargs["w2_preparation_runtime"] is w2_runtime
    assert set(observed_kwargs) == expected_keys
    assert app.pipeline_result is result
    assert app.pipeline_error is None


def test_tui_rejects_active_execution_without_exact_w2_runtime() -> None:
    identity = _raw_request_execution_identity_from_env(_actions_env())
    assurance_authority = raw_request_assurance_authority(source_sha=_SOURCE_SHA)

    with pytest.raises(TypeError, match="exact W2 preparation runtime"):
        NbaDbDashboard(
            raw_request_execution_identity=identity,
            raw_request_assurance_authority=assurance_authority,
        )
    with pytest.raises(TypeError, match="requires an active execution identity"):
        NbaDbDashboard(w2_preparation_runtime=_w2_runtime())


@pytest.mark.parametrize("root_case", ["missing", "invalid_mode"])
def test_active_pipeline_rejects_missing_or_invalid_w2_roots_before_provider_work(
    tmp_path: Path,
    root_case: str,
) -> None:
    assurance_authority = raw_request_assurance_authority(source_sha=_SOURCE_SHA)
    constructed = False
    provider_work_started = False

    class FakeOrchestrator:
        def __init__(self, **_kwargs: object) -> None:
            nonlocal constructed
            constructed = True

    async def run_pipeline(_orchestrator: object) -> PipelineResult:
        nonlocal provider_work_started
        provider_work_started = True
        return _result()

    environ = _actions_env()
    if root_case == "invalid_mode":
        body_root = tmp_path / "body"
        packet_root = tmp_path / "packet"
        body_root.mkdir(mode=0o700)
        packet_root.mkdir(mode=0o700)
        body_root.chmod(0o755)
        packet_root.chmod(0o700)
        environ.update(
            NBADB_W2_BODY_BLOB_ROOT=str(body_root),
            NBADB_W2_DECLARED_BODYLESS_PACKET_ROOT=str(packet_root),
        )

    with (
        patch.dict("os.environ", environ, clear=True),
        patch(
            "nbadb.cli.commands._helpers._raw_request_assurance_authority_from_env",
            return_value=assurance_authority,
        ),
        pytest.raises(W2RuntimeEnvironmentError),
    ):
        _run_pipeline(
            "backfill",
            run_pipeline,
            _build_settings(),
            verbose=True,
            orchestrator_cls=FakeOrchestrator,
        )

    assert not constructed
    assert not provider_work_started


def test_active_pipeline_rejects_foreign_w2_runtime_before_provider_work() -> None:
    assurance_authority = raw_request_assurance_authority(source_sha=_SOURCE_SHA)
    constructed = False
    provider_work_started = False

    class FakeOrchestrator:
        def __init__(self, **_kwargs: object) -> None:
            nonlocal constructed
            constructed = True

    async def run_pipeline(_orchestrator: object) -> PipelineResult:
        nonlocal provider_work_started
        provider_work_started = True
        return _result()

    with (
        patch.dict("os.environ", _actions_env(), clear=True),
        patch(
            "nbadb.cli.commands._helpers._raw_request_assurance_authority_from_env",
            return_value=assurance_authority,
        ),
        patch(
            "nbadb.orchestrate.w2_runtime_environment.w2_source_call_preparation_runtime_from_env",
            return_value=object(),
        ),
        pytest.raises(W2RuntimeEnvironmentError, match="foreign W2 preparation runtime"),
    ):
        _run_pipeline(
            "backfill",
            run_pipeline,
            _build_settings(),
            verbose=True,
            orchestrator_cls=FakeOrchestrator,
        )

    assert not constructed
    assert not provider_work_started


def test_invalid_opt_in_fails_before_orchestrator_construction() -> None:
    constructed = False

    class FakeOrchestrator:
        def __init__(self, **_kwargs: object) -> None:
            nonlocal constructed
            constructed = True

    async def run_pipeline(_orchestrator: object) -> PipelineResult:
        return _result()

    environ = _actions_env(opt_in="yes")
    with (
        patch.dict("os.environ", environ, clear=True),
        patch("nbadb.cli.commands._helpers.sys.stdout") as stdout,
        pytest.raises(RawRequestExecutionEnvironmentError),
    ):
        stdout.isatty.return_value = False
        _run_pipeline(
            "backfill",
            run_pipeline,
            _build_settings(),
            verbose=True,
            orchestrator_cls=FakeOrchestrator,
        )

    assert not constructed
