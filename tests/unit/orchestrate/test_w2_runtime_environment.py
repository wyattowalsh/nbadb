"""Adversarial tests for explicit production W2 runtime admission."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from nbadb.contracts.assurance import FIELD_FATE_STRUCTURE_NAME
from nbadb.contracts.field_fate_structure import (
    FieldFateStructureV1,
    compile_field_fate_structure,
)
from nbadb.orchestrate import raw_request_assurance as assurance_module
from nbadb.orchestrate import w2_runtime_environment as runtime_module
from nbadb.orchestrate import w2_source_call_preparation as preparation_module
from nbadb.orchestrate.body_blob_store import BodyBlobStore
from nbadb.orchestrate.declared_bodyless_packet_store import (
    DeclaredBodylessPacketStore,
)
from nbadb.orchestrate.raw_request_assurance import RawRequestAssuranceAuthorityV2
from nbadb.orchestrate.raw_request_context import RawRequestExecutionIdentityV1
from nbadb.orchestrate.w2_runtime_environment import (
    W2_BODY_BLOB_ROOT_ENV,
    W2_DECLARED_BODYLESS_PACKET_ROOT_ENV,
    W2RuntimeEnvironmentError,
    w2_source_call_preparation_runtime_from_env,
)
from nbadb.orchestrate.w2_source_call_preparation import (
    W2SourceCallPreparationRuntime,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


_SOURCE_SHA = "a" * 40


@lru_cache(maxsize=1)
def _field_fate() -> FieldFateStructureV1:
    return compile_field_fate_structure(upstream_root="")


def _execution(*, source_sha: str = _SOURCE_SHA) -> RawRequestExecutionIdentityV1:
    return RawRequestExecutionIdentityV1(
        source_sha=source_sha,
        run_id=101,
        run_attempt=2,
        chain_id="chain",
        lane_id="lane",
    )


def _authority(
    field_fate_sha256: str,
    *,
    source_sha: str = _SOURCE_SHA,
    field_name_type: type[str] = str,
) -> RawRequestAssuranceAuthorityV2:
    field_children = tuple(
        (
            field_name_type(name),
            field_fate_sha256 if name == FIELD_FATE_STRUCTURE_NAME else f"{index + 1:064x}",
        )
        for index, name in enumerate(assurance_module._FIELD_AUTHORITY_CHILD_NAMES)  # noqa: SLF001
    )
    model_children = tuple(
        (name, f"{index + 32:064x}")
        for index, name in enumerate(assurance_module._MODEL_AUTHORITY_CHILD_NAMES)  # noqa: SLF001
    )
    common = {
        "source_sha": source_sha,
        "assurance_admission_sha256": "1" * 64,
        "assurance_manifest_sha256": "2" * 64,
        "generation_semantic_sha256": "3" * 64,
        "generation_index_sha256": "4" * 64,
        "provider_evidence_sha256": "5" * 64,
        "provider_authority_sha256": "6" * 64,
    }
    return RawRequestAssuranceAuthorityV2(
        **common,
        field_children=field_children,
        model_children=model_children,
        field_authority_sha256=assurance_module._authority_digest(  # noqa: SLF001
            kind="nbadb_raw_request_field_authority",
            children=field_children,
            **common,
        ),
        model_authority_sha256=assurance_module._authority_digest(  # noqa: SLF001
            kind="nbadb_raw_request_model_authority",
            children=model_children,
            **common,
        ),
        validation_provenance_sha256="7" * 64,
    )


def _roots(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    body = tmp_path / "body"
    packet = tmp_path / "packet"
    body.mkdir(mode=0o700)
    packet.mkdir(mode=0o700)
    body.chmod(0o700)
    packet.chmod(0o700)
    return (
        body,
        packet,
        {
            W2_BODY_BLOB_ROOT_ENV: str(body),
            W2_DECLARED_BODYLESS_PACKET_ROOT_ENV: str(packet),
        },
    )


def _admit_assurance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runtime_module,
        "validate_raw_request_assurance_authority",
        lambda value: value,
    )


def _fast_field_fate(
    monkeypatch: pytest.MonkeyPatch,
    field_fate: FieldFateStructureV1,
) -> None:
    monkeypatch.setattr(
        runtime_module,
        "_replay_current_field_fate",
        lambda: field_fate,
    )
    monkeypatch.setattr(
        preparation_module,
        "validate_field_fate_structure",
        lambda *_args, **_kwargs: None,
    )


class _GetOnlyEnvironment(Mapping[str, str]):
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values
        self.reads: list[str] = []

    def __iter__(self) -> Iterator[str]:
        raise AssertionError("environment enumeration is forbidden")

    def __len__(self) -> int:
        raise AssertionError("environment sizing is forbidden")

    def __getitem__(self, key: str) -> str:
        self.reads.append(key)
        return self.values[key]


def test_inactive_execution_returns_none_without_touching_other_authorities() -> None:
    class _ExplodingEnvironment:
        def get(self, _key: str) -> str:
            raise AssertionError("inactive execution consulted the environment")

    assert (
        w2_source_call_preparation_runtime_from_env(
            None,
            object(),  # type: ignore[arg-type]
            _ExplodingEnvironment(),  # type: ignore[arg-type]
        )
        is None
    )


def test_constructs_exact_run_bound_runtime_after_full_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body, packet, environ = _roots(tmp_path)
    field_fate = _field_fate()
    execution = _execution()
    assurance = _authority(field_fate.identity_sha256)
    observed: list[tuple[str, Path, RawRequestExecutionIdentityV1]] = []
    original_body = runtime_module._construct_body_blob_store  # noqa: SLF001
    original_packet = runtime_module._construct_declared_bodyless_packet_store  # noqa: SLF001

    def _body(root: Path, exact_execution: RawRequestExecutionIdentityV1) -> BodyBlobStore:
        observed.append(("body", root, exact_execution))
        return original_body(root, exact_execution)

    def _packet(
        root: Path,
        exact_execution: RawRequestExecutionIdentityV1,
    ) -> DeclaredBodylessPacketStore:
        observed.append(("packet", root, exact_execution))
        return original_packet(root, exact_execution)

    _admit_assurance(monkeypatch)
    monkeypatch.setattr(runtime_module, "_compile_current_field_fate", lambda: field_fate)
    monkeypatch.setattr(runtime_module, "_construct_body_blob_store", _body)
    monkeypatch.setattr(runtime_module, "_construct_declared_bodyless_packet_store", _packet)

    runtime = w2_source_call_preparation_runtime_from_env(execution, assurance, environ)

    assert type(runtime) is W2SourceCallPreparationRuntime
    assert type(runtime.body_blob_store) is BodyBlobStore
    assert type(runtime.declared_bodyless_packet_store) is DeclaredBodylessPacketStore
    assert runtime.field_fate == field_fate
    assert runtime.field_fate is not field_fate
    assert runtime.known_secrets == ()
    assert observed == [("body", body, execution), ("packet", packet, execution)]
    assert (body / ".body-blob-store.lock").is_file()
    assert (packet / ".declared-bodyless-packet.lock").is_file()


def test_reads_only_the_two_allowlisted_environment_keys_without_enumeration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _body, _packet, values = _roots(tmp_path)
    values["SECRET_TOKEN"] = "must-not-be-read"
    environ = _GetOnlyEnvironment(values)
    field_fate = _field_fate()
    _admit_assurance(monkeypatch)
    _fast_field_fate(monkeypatch, field_fate)

    runtime = w2_source_call_preparation_runtime_from_env(
        _execution(),
        _authority(field_fate.identity_sha256),
        environ,  # type: ignore[arg-type]
    )

    assert type(runtime) is W2SourceCallPreparationRuntime
    assert environ.reads == [
        W2_BODY_BLOB_ROOT_ENV,
        W2_DECLARED_BODYLESS_PACKET_ROOT_ENV,
    ]


def test_active_execution_requires_authority_before_environment_access() -> None:
    class _ExplodingEnvironment:
        def get(self, _key: str) -> str:
            raise AssertionError("invalid assurance consulted the environment")

    with pytest.raises(W2RuntimeEnvironmentError, match="exact Raw Authority V2"):
        w2_source_call_preparation_runtime_from_env(
            _execution(),
            None,
            _ExplodingEnvironment(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("foreign", [object(), True, "active"])
def test_rejects_foreign_execution_types_before_authority_or_environment(
    foreign: object,
) -> None:
    with pytest.raises(W2RuntimeEnvironmentError, match="exact active execution"):
        w2_source_call_preparation_runtime_from_env(  # type: ignore[arg-type]
            foreign,
            None,
            {},
        )


def test_rejects_execution_and_assurance_subclasses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExecutionSubclass(RawRequestExecutionIdentityV1):
        pass

    class AssuranceSubclass(RawRequestAssuranceAuthorityV2):
        pass

    field_fate = _field_fate()
    authority = _authority(field_fate.identity_sha256)
    authority_values = {
        item.name: getattr(authority, item.name) for item in fields(RawRequestAssuranceAuthorityV2)
    }
    _body, _packet, environ = _roots(tmp_path)
    _admit_assurance(monkeypatch)

    with pytest.raises(W2RuntimeEnvironmentError, match="exact active execution"):
        w2_source_call_preparation_runtime_from_env(
            ExecutionSubclass(**_execution().to_dict()),
            authority,
            environ,
        )
    with pytest.raises(W2RuntimeEnvironmentError, match="exact Raw Authority V2"):
        w2_source_call_preparation_runtime_from_env(
            _execution(),
            AssuranceSubclass(**authority_values),
            environ,
        )


def test_rejects_mutated_execution_and_foreign_assurance_scalars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TextSubclass(str):
        pass

    field_fate = _field_fate()
    _body, _packet, environ = _roots(tmp_path)
    _admit_assurance(monkeypatch)
    execution = _execution()
    object.__setattr__(execution, "run_id", True)

    with pytest.raises(W2RuntimeEnvironmentError, match="failed exact replay"):
        w2_source_call_preparation_runtime_from_env(
            execution,
            _authority(field_fate.identity_sha256),
            environ,
        )
    with pytest.raises(W2RuntimeEnvironmentError, match="foreign scalar type"):
        w2_source_call_preparation_runtime_from_env(
            _execution(),
            _authority(field_fate.identity_sha256, source_sha=TextSubclass(_SOURCE_SHA)),
            environ,
        )


def test_assurance_validation_is_sanitized_and_replayed_twice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    field_fate = _field_fate()
    authority = _authority(field_fate.identity_sha256)
    _body, _packet, environ = _roots(tmp_path)
    seen: list[RawRequestAssuranceAuthorityV2] = []

    def _validate(value: object) -> object:
        assert type(value) is RawRequestAssuranceAuthorityV2
        seen.append(value)
        return value

    monkeypatch.setattr(runtime_module, "validate_raw_request_assurance_authority", _validate)
    _fast_field_fate(monkeypatch, field_fate)

    w2_source_call_preparation_runtime_from_env(_execution(), authority, environ)

    assert len(seen) == 2
    assert seen[0] is authority
    assert seen[1] is not authority
    assert seen[1] == authority


def test_sanitizes_hostile_assurance_error_and_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    field_fate = _field_fate()
    authority = _authority(field_fate.identity_sha256)
    _body, _packet, environ = _roots(tmp_path)

    def _explode(_value: object) -> object:
        raise W2RuntimeEnvironmentError("hostile-secret-value")

    monkeypatch.setattr(runtime_module, "validate_raw_request_assurance_authority", _explode)
    with pytest.raises(W2RuntimeEnvironmentError) as failure:
        w2_source_call_preparation_runtime_from_env(_execution(), authority, environ)
    assert str(failure.value) == "W2 runtime assurance authority failed independent validation"
    assert "hostile-secret-value" not in str(failure.value)

    monkeypatch.setattr(
        runtime_module,
        "validate_raw_request_assurance_authority",
        lambda _value: object(),
    )
    with pytest.raises(W2RuntimeEnvironmentError, match="returned foreign authority"):
        w2_source_call_preparation_runtime_from_env(_execution(), authority, environ)


def test_rejects_replay_validator_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    field_fate = _field_fate()
    authority = _authority(field_fate.identity_sha256)
    _body, _packet, environ = _roots(tmp_path)

    monkeypatch.setattr(
        runtime_module,
        "validate_raw_request_assurance_authority",
        lambda _value: authority,
    )
    with pytest.raises(W2RuntimeEnvironmentError, match="replay validation returned foreign"):
        w2_source_call_preparation_runtime_from_env(_execution(), authority, environ)


def test_rejects_assurance_source_mismatch_before_root_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    field_fate = _field_fate()
    _admit_assurance(monkeypatch)

    with pytest.raises(W2RuntimeEnvironmentError, match="source differs"):
        w2_source_call_preparation_runtime_from_env(
            _execution(),
            _authority(field_fate.identity_sha256, source_sha="b" * 40),
            {},
        )


def test_sanitizes_hostile_environment_mapping_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class HostileEnvironment(Mapping[str, str]):
        def __iter__(self) -> Iterator[str]:
            raise AssertionError("hostile mapping must not be enumerated")

        def __len__(self) -> int:
            raise AssertionError("hostile mapping must not be sized")

        def __getitem__(self, key: str) -> str:
            raise RuntimeError(f"hostile-secret-value:{key}")

    field_fate = _field_fate()
    _admit_assurance(monkeypatch)
    with pytest.raises(W2RuntimeEnvironmentError) as failure:
        w2_source_call_preparation_runtime_from_env(
            _execution(),
            _authority(field_fate.identity_sha256),
            HostileEnvironment(),  # type: ignore[arg-type]
        )
    assert str(failure.value) == "W2 runtime root environment is unreadable"
    assert "hostile-secret-value" not in str(failure.value)


def test_rejects_nonmapping_environment_before_calling_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ForeignEnvironment:
        def get(self, _key: str) -> str:
            raise AssertionError("foreign environment was dereferenced")

    field_fate = _field_fate()
    _admit_assurance(monkeypatch)
    with pytest.raises(W2RuntimeEnvironmentError, match="mapping authority"):
        w2_source_call_preparation_runtime_from_env(
            _execution(),
            _authority(field_fate.identity_sha256),
            ForeignEnvironment(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "bad_value",
    [None, Path("/tmp"), True, 7],
)
def test_root_environment_values_require_exact_strings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad_value: object,
) -> None:
    _body, packet, _environ = _roots(tmp_path)
    field_fate = _field_fate()
    _admit_assurance(monkeypatch)
    environ: dict[str, Any] = {
        W2_BODY_BLOB_ROOT_ENV: bad_value,
        W2_DECLARED_BODYLESS_PACKET_ROOT_ENV: str(packet),
    }

    with pytest.raises(W2RuntimeEnvironmentError, match="environment is incomplete"):
        w2_source_call_preparation_runtime_from_env(
            _execution(),
            _authority(field_fate.identity_sha256),
            environ,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "bad_root",
    [
        "",
        "relative",
        "/",
        "//tmp",
        "/tmp/../tmp",
        "/tmp/",
        "/" + "x" * 4097,
        "/tmp/\x00x",
    ],
)
def test_rejects_noncanonical_or_unbounded_root_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad_root: str,
) -> None:
    _body, packet, _environ = _roots(tmp_path)
    field_fate = _field_fate()
    _admit_assurance(monkeypatch)

    with pytest.raises(W2RuntimeEnvironmentError, match="canonical bounded absolute path"):
        w2_source_call_preparation_runtime_from_env(
            _execution(),
            _authority(field_fate.identity_sha256),
            {
                W2_BODY_BLOB_ROOT_ENV: bad_root,
                W2_DECLARED_BODYLESS_PACKET_ROOT_ENV: str(packet),
            },
        )


def test_requires_preexisting_directory_and_never_creates_missing_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _body, packet, _environ = _roots(tmp_path)
    missing = tmp_path / "missing"
    field_fate = _field_fate()
    _admit_assurance(monkeypatch)

    with pytest.raises(W2RuntimeEnvironmentError, match="root is unavailable"):
        w2_source_call_preparation_runtime_from_env(
            _execution(),
            _authority(field_fate.identity_sha256),
            {
                W2_BODY_BLOB_ROOT_ENV: str(missing),
                W2_DECLARED_BODYLESS_PACKET_ROOT_ENV: str(packet),
            },
        )
    assert not missing.exists()


def test_rejects_file_final_symlink_and_symlinked_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    field_fate = _field_fate()
    _admit_assurance(monkeypatch)
    body, packet, _environ = _roots(tmp_path)
    regular_file = tmp_path / "regular"
    regular_file.write_text("not a directory", encoding="utf-8")
    regular_file.chmod(0o700)
    link = tmp_path / "link"
    link.symlink_to(body, target_is_directory=True)
    parent = tmp_path / "parent"
    nested = parent / "nested"
    parent.mkdir(mode=0o700)
    nested.mkdir(mode=0o700)
    parent.chmod(0o700)
    nested.chmod(0o700)
    parent_link = tmp_path / "parent-link"
    parent_link.symlink_to(parent, target_is_directory=True)

    for bad_path in (regular_file, link, parent_link / "nested"):
        with pytest.raises(W2RuntimeEnvironmentError, match="non-directory authority"):
            w2_source_call_preparation_runtime_from_env(
                _execution(),
                _authority(field_fate.identity_sha256),
                {
                    W2_BODY_BLOB_ROOT_ENV: str(bad_path),
                    W2_DECLARED_BODYLESS_PACKET_ROOT_ENV: str(packet),
                },
            )


def test_requires_exact_mode_and_current_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body, _packet, environ = _roots(tmp_path)
    field_fate = _field_fate()
    _admit_assurance(monkeypatch)
    body.chmod(0o750)

    with pytest.raises(W2RuntimeEnvironmentError, match="owner-only 0700"):
        w2_source_call_preparation_runtime_from_env(
            _execution(),
            _authority(field_fate.identity_sha256),
            environ,
        )
    body.chmod(0o700)
    actual_uid = runtime_module.os.geteuid()
    monkeypatch.setattr(runtime_module.os, "geteuid", lambda: actual_uid + 1)
    with pytest.raises(W2RuntimeEnvironmentError, match="owner-only 0700"):
        w2_source_call_preparation_runtime_from_env(
            _execution(),
            _authority(field_fate.identity_sha256),
            environ,
        )


def test_rejects_same_and_nested_root_aliases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = tmp_path / "body"
    nested = body / "nested"
    body.mkdir(mode=0o700)
    nested.mkdir(mode=0o700)
    body.chmod(0o700)
    nested.chmod(0o700)
    field_fate = _field_fate()
    _admit_assurance(monkeypatch)

    for packet in (body, nested):
        with pytest.raises(W2RuntimeEnvironmentError, match="overlap or alias"):
            w2_source_call_preparation_runtime_from_env(
                _execution(),
                _authority(field_fate.identity_sha256),
                {
                    W2_BODY_BLOB_ROOT_ENV: str(body),
                    W2_DECLARED_BODYLESS_PACKET_ROOT_ENV: str(packet),
                },
            )


def test_field_fate_compile_replay_and_child_digest_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    field_fate = _field_fate()
    _body, _packet, environ = _roots(tmp_path)
    _admit_assurance(monkeypatch)

    def _explode() -> FieldFateStructureV1:
        raise W2RuntimeEnvironmentError("hostile-secret-value")

    monkeypatch.setattr(runtime_module, "_compile_current_field_fate", _explode)
    with pytest.raises(W2RuntimeEnvironmentError) as failure:
        w2_source_call_preparation_runtime_from_env(
            _execution(),
            _authority(field_fate.identity_sha256),
            environ,
        )
    assert str(failure.value) == "W2 runtime current field-fate authority could not be compiled"
    assert "hostile-secret-value" not in str(failure.value)

    monkeypatch.setattr(runtime_module, "_compile_current_field_fate", lambda: object())
    with pytest.raises(W2RuntimeEnvironmentError, match="foreign authority"):
        w2_source_call_preparation_runtime_from_env(
            _execution(),
            _authority(field_fate.identity_sha256),
            environ,
        )

    monkeypatch.setattr(runtime_module, "_compile_current_field_fate", lambda: field_fate)
    with pytest.raises(W2RuntimeEnvironmentError, match="assurance child identity"):
        w2_source_call_preparation_runtime_from_env(
            _execution(),
            _authority("0" * 64),
            environ,
        )


def test_rejects_mutated_and_subclassed_field_fate_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FieldFateSubclass(FieldFateStructureV1):
        pass

    field_fate = _field_fate()
    _body, _packet, environ = _roots(tmp_path)
    _admit_assurance(monkeypatch)
    subclassed = FieldFateSubclass(
        provider_sources=field_fate.provider_sources,
        route_bindings=field_fate.route_bindings,
        storage_sinks=field_fate.storage_sinks,
        lossless_bindings=field_fate.lossless_bindings,
        blockers=field_fate.blockers,
    )
    monkeypatch.setattr(runtime_module, "_compile_current_field_fate", lambda: subclassed)
    with pytest.raises(W2RuntimeEnvironmentError, match="foreign authority"):
        w2_source_call_preparation_runtime_from_env(
            _execution(),
            _authority(field_fate.identity_sha256),
            environ,
        )

    mutated = FieldFateStructureV1(
        provider_sources=field_fate.provider_sources,
        route_bindings=field_fate.route_bindings,
        storage_sinks=field_fate.storage_sinks,
        lossless_bindings=field_fate.lossless_bindings,
        blockers=field_fate.blockers,
    )
    object.__setattr__(mutated, "provider_sources", object())
    monkeypatch.setattr(runtime_module, "_compile_current_field_fate", lambda: mutated)
    with pytest.raises(W2RuntimeEnvironmentError, match="failed exact replay"):
        w2_source_call_preparation_runtime_from_env(
            _execution(),
            _authority(field_fate.identity_sha256),
            environ,
        )


@pytest.mark.parametrize(
    ("helper_name", "expected_message"),
    [
        ("_construct_body_blob_store", "body-blob store construction failed"),
        (
            "_construct_declared_bodyless_packet_store",
            "declared-bodyless store construction failed",
        ),
        ("_construct_runtime", "preparation runtime construction failed"),
    ],
)
def test_sanitizes_hostile_dependency_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    helper_name: str,
    expected_message: str,
) -> None:
    field_fate = _field_fate()
    _body, _packet, environ = _roots(tmp_path)
    _admit_assurance(monkeypatch)
    _fast_field_fate(monkeypatch, field_fate)

    def _explode(*_args: object, **_kwargs: object) -> object:
        raise W2RuntimeEnvironmentError("hostile-secret-value")

    monkeypatch.setattr(runtime_module, helper_name, _explode)
    with pytest.raises(W2RuntimeEnvironmentError) as failure:
        w2_source_call_preparation_runtime_from_env(
            _execution(),
            _authority(field_fate.identity_sha256),
            environ,
        )
    assert expected_message in str(failure.value)
    assert "hostile-secret-value" not in str(failure.value)


@pytest.mark.parametrize(
    ("helper_name", "expected_message"),
    [
        ("_construct_body_blob_store", "body-blob store construction returned"),
        (
            "_construct_declared_bodyless_packet_store",
            "declared-bodyless store construction returned",
        ),
        ("_construct_runtime", "runtime returned foreign authority"),
    ],
)
def test_rejects_foreign_dependency_returns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    helper_name: str,
    expected_message: str,
) -> None:
    field_fate = _field_fate()
    _body, _packet, environ = _roots(tmp_path)
    _admit_assurance(monkeypatch)
    _fast_field_fate(monkeypatch, field_fate)
    monkeypatch.setattr(runtime_module, helper_name, lambda *_args, **_kwargs: object())

    with pytest.raises(W2RuntimeEnvironmentError, match=expected_message):
        w2_source_call_preparation_runtime_from_env(
            _execution(),
            _authority(field_fate.identity_sha256),
            environ,
        )


def test_detects_root_permission_mutation_after_store_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    field_fate = _field_fate()
    body, _packet, environ = _roots(tmp_path)
    _admit_assurance(monkeypatch)
    _fast_field_fate(monkeypatch, field_fate)
    original = runtime_module._construct_body_blob_store  # noqa: SLF001

    def _mutate(
        root: Path,
        execution: RawRequestExecutionIdentityV1,
    ) -> BodyBlobStore:
        store = original(root, execution)
        root.chmod(0o755)
        return store

    monkeypatch.setattr(runtime_module, "_construct_body_blob_store", _mutate)
    with pytest.raises(W2RuntimeEnvironmentError, match="owner-only 0700"):
        w2_source_call_preparation_runtime_from_env(
            _execution(),
            _authority(field_fate.identity_sha256),
            environ,
        )
    assert body.stat().st_mode & 0o777 == 0o755


def test_rejects_runtime_that_mutates_known_secret_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    field_fate = _field_fate()
    _body, _packet, environ = _roots(tmp_path)
    _admit_assurance(monkeypatch)
    _fast_field_fate(monkeypatch, field_fate)
    original = runtime_module._construct_runtime  # noqa: SLF001

    def _mutate(
        body_store: BodyBlobStore,
        packet_store: DeclaredBodylessPacketStore,
        exact_field_fate: FieldFateStructureV1,
    ) -> W2SourceCallPreparationRuntime:
        runtime = original(body_store, packet_store, exact_field_fate)
        object.__setattr__(runtime, "known_secrets", ("hostile-secret-value",))
        return runtime

    monkeypatch.setattr(runtime_module, "_construct_runtime", _mutate)
    with pytest.raises(W2RuntimeEnvironmentError, match="foreign authority") as failure:
        w2_source_call_preparation_runtime_from_env(
            _execution(),
            _authority(field_fate.identity_sha256),
            environ,
        )
    assert "hostile-secret-value" not in str(failure.value)


def test_field_fate_compile_path_never_reads_ambient_upstream_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    field_fate = _field_fate()
    _body, _packet, environ = _roots(tmp_path)
    _admit_assurance(monkeypatch)
    monkeypatch.setattr(
        preparation_module,
        "validate_field_fate_structure",
        lambda *_args, **_kwargs: None,
    )

    def _forbidden_getenv(_name: str, _default: object = None) -> object:
        raise AssertionError("ambient upstream-root lookup is forbidden")

    monkeypatch.setattr(runtime_module.os, "getenv", _forbidden_getenv)

    runtime = w2_source_call_preparation_runtime_from_env(
        _execution(),
        _authority(field_fate.identity_sha256),
        environ,
    )

    assert type(runtime) is W2SourceCallPreparationRuntime
