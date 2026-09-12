from __future__ import annotations

import gzip
import hashlib
import json
import os
from typing import TYPE_CHECKING, cast

import pytest

import nbadb.core.artifact_identity as artifact_identity
from nbadb.core.artifact_identity import (
    ASSURED_ARTIFACT_MANIFEST_NAME,
    SUCCESSOR_TERMINAL_ASSURANCE_REPORT_NAME,
    assert_no_private_capture_sentinels,
    build_assured_artifact_manifest,
    inventory_regular_tree,
    main,
    verify_assured_artifact_manifest,
)
from nbadb.extract.bronze import BronzeCaptureStore, BronzeLimits

if TYPE_CHECKING:
    from pathlib import Path

_SOURCE_SHA = "a" * 40
_COVERAGE_FINGERPRINT = "b" * 64


def _write_artifact(root: Path) -> None:
    (root / "parquet" / "dim_player").mkdir(parents=True)
    (root / "nba.duckdb").write_bytes(b"duckdb")
    (root / "parquet" / "dim_player" / "part-0.parquet").write_bytes(b"parquet")


def test_build_and_verify_manifest_round_trip(tmp_path: Path) -> None:
    _write_artifact(tmp_path)

    manifest_path = build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )
    manifest = verify_assured_artifact_manifest(
        tmp_path,
        expected_chain_id="full-20260711",
        expected_source_sha=_SOURCE_SHA,
        expected_coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )

    assert manifest_path == tmp_path / ASSURED_ARTIFACT_MANIFEST_NAME
    assert manifest["file_count"] == 2
    assert manifest["bytes"] == len(b"duckdbparquet")
    assert [entry["path"] for entry in manifest["files"]] == [
        "nba.duckdb",
        "parquet/dim_player/part-0.parquet",
    ]


def test_general_inventory_supports_caller_owned_exclusions(tmp_path: Path) -> None:
    (tmp_path / "included.bin").write_bytes(b"included")
    (tmp_path / "private.lock").write_bytes(b"lock")

    inventory = inventory_regular_tree(
        tmp_path,
        excluded_paths=frozenset({"private.lock"}),
    )

    assert inventory == [
        {
            "path": "included.bin",
            "bytes": len(b"included"),
            "sha256": hashlib.sha256(b"included").hexdigest(),
        }
    ]


def test_artifact_identity_apis_accept_exact_expected_root_identity(tmp_path: Path) -> None:
    _write_artifact(tmp_path)
    observed = tmp_path.stat()
    expected = (observed.st_dev, observed.st_ino)

    inventory = inventory_regular_tree(tmp_path, expected_root_identity=expected)
    assert inventory
    assert_no_private_capture_sentinels(tmp_path, expected_root_identity=expected)
    manifest_path = build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
        expected_root_identity=expected,
    )
    manifest = verify_assured_artifact_manifest(
        tmp_path,
        expected_root_identity=expected,
    )

    assert manifest_path == tmp_path / ASSURED_ARTIFACT_MANIFEST_NAME
    assert manifest["file_count"] == len(inventory)


@pytest.mark.parametrize("invalid_identity", [True, 1.5, [1, 2], (-1, 2)])
def test_artifact_identity_apis_reject_invalid_expected_root_identity(
    tmp_path: Path,
    invalid_identity: object,
) -> None:
    _write_artifact(tmp_path)
    build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )
    manifest_path = tmp_path / ASSURED_ARTIFACT_MANIFEST_NAME
    before = manifest_path.read_bytes()
    invalid = cast("tuple[int, int]", invalid_identity)

    with pytest.raises(ValueError, match="expected root identity is invalid"):
        inventory_regular_tree(tmp_path, expected_root_identity=invalid)
    with pytest.raises(ValueError, match="expected root identity is invalid"):
        assert_no_private_capture_sentinels(tmp_path, expected_root_identity=invalid)
    with pytest.raises(ValueError, match="expected root identity is invalid"):
        build_assured_artifact_manifest(
            tmp_path,
            chain_id="full-20260711",
            source_sha=_SOURCE_SHA,
            coverage_fingerprint=_COVERAGE_FINGERPRINT,
            expected_root_identity=invalid,
        )
    with pytest.raises(ValueError, match="expected root identity is invalid"):
        verify_assured_artifact_manifest(tmp_path, expected_root_identity=invalid)

    assert manifest_path.read_bytes() == before


def test_artifact_identity_rejects_foreign_root_before_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_artifact(tmp_path)
    manifest_path = build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )
    before = manifest_path.read_bytes()
    observed = tmp_path.stat()
    foreign = (observed.st_dev, observed.st_ino + 1)

    def unexpected_effect(*args: object, **kwargs: object) -> object:
        raise AssertionError("artifact traversal must not run for foreign root authority")

    monkeypatch.setattr(artifact_identity, "_scan_public_tree_descriptor", unexpected_effect)
    monkeypatch.setattr(artifact_identity, "_inventory_from_descriptor", unexpected_effect)
    monkeypatch.setattr(artifact_identity, "_read_manifest", unexpected_effect)

    with pytest.raises(ValueError, match="root differs from expected authority"):
        inventory_regular_tree(tmp_path, expected_root_identity=foreign)
    with pytest.raises(ValueError, match="root differs from expected authority"):
        assert_no_private_capture_sentinels(tmp_path, expected_root_identity=foreign)
    with pytest.raises(ValueError, match="root differs from expected authority"):
        build_assured_artifact_manifest(
            tmp_path,
            chain_id="full-20260711",
            source_sha=_SOURCE_SHA,
            coverage_fingerprint=_COVERAGE_FINGERPRINT,
            expected_root_identity=foreign,
        )
    with pytest.raises(ValueError, match="root differs from expected authority"):
        verify_assured_artifact_manifest(tmp_path, expected_root_identity=foreign)

    assert manifest_path.read_bytes() == before


def test_verify_rejects_tampered_artifact(tmp_path: Path) -> None:
    _write_artifact(tmp_path)
    build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )
    (tmp_path / "nba.duckdb").write_bytes(b"tampered")

    with pytest.raises(ValueError, match="contents do not match"):
        verify_assured_artifact_manifest(tmp_path)


@pytest.mark.parametrize("mutation", ["add", "unlink", "replace", "rewrite"])
def test_verify_rejects_directory_entry_mutation_after_file_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    root = tmp_path / "public"
    root.mkdir()
    data_path = root / "data.bin"
    data_path.write_bytes(b"original")
    build_assured_artifact_manifest(
        root,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )
    replacement = tmp_path / "foreign.bin"
    replacement.write_bytes(b"foreign")
    original_hash = artifact_identity._hash_regular_descriptor
    mutated = False

    def mutate_after_hash(descriptor: int, *, display_path: str) -> tuple[int, str]:
        nonlocal mutated
        result = original_hash(descriptor, display_path=display_path)
        if display_path == "data.bin" and not mutated:
            mutated = True
            if mutation == "add":
                (root / "extra.bin").write_bytes(b"extra")
            elif mutation == "unlink":
                data_path.unlink()
            elif mutation == "replace":
                os.replace(replacement, data_path)
            else:
                data_path.write_bytes(b"foreign-in-place")
        return result

    monkeypatch.setattr(artifact_identity, "_hash_regular_descriptor", mutate_after_hash)

    with pytest.raises(ValueError, match="changed"):
        verify_assured_artifact_manifest(root)

    assert mutated is True


@pytest.mark.parametrize("mutation", ["add", "unlink", "replace", "rewrite"])
def test_private_sentinel_scan_rejects_mutation_after_file_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    root = tmp_path / "public"
    root.mkdir()
    data_path = root / "data.bin"
    data_path.write_bytes(b"public")
    replacement = tmp_path / "foreign.bin"
    replacement.write_bytes(b'{"kind":"logical_call"}')
    original_scan = artifact_identity._scan_descriptor_for_private_capture
    mutated = False

    def mutate_after_scan(descriptor: int, *, display_path: str) -> None:
        nonlocal mutated
        original_scan(descriptor, display_path=display_path)
        if display_path == "data.bin" and not mutated:
            mutated = True
            if mutation == "add":
                (root / "extra.bin").write_bytes(b'{"kind":"logical_call"}')
            elif mutation == "unlink":
                data_path.unlink()
            elif mutation == "replace":
                os.replace(replacement, data_path)
            else:
                data_path.write_bytes(b'{"kind":"logical_call"}')

    monkeypatch.setattr(
        artifact_identity,
        "_scan_descriptor_for_private_capture",
        mutate_after_scan,
    )

    with pytest.raises(ValueError, match="changed"):
        assert_no_private_capture_sentinels(root)

    assert mutated is True


@pytest.mark.parametrize(
    "sentinel",
    [
        b"private_parser_input_generation",
        b"nbadb_exact_decoded_response_text_utf8",
        b"nba_api_static_canonical_json_utf8",
    ],
)
def test_public_artifact_rejects_private_capture_sentinels(
    tmp_path: Path,
    sentinel: bytes,
) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "leak.bin").write_bytes(b"prefix-" + sentinel + b"-suffix")

    with pytest.raises(ValueError, match="private parser-input sentinel"):
        assert_no_private_capture_sentinels(tmp_path)
    with pytest.raises(ValueError, match="private parser-input sentinel"):
        build_assured_artifact_manifest(
            tmp_path,
            chain_id="full-20260711",
            source_sha=_SOURCE_SHA,
            coverage_fingerprint=_COVERAGE_FINGERPRINT,
        )


def test_successor_report_exclusion_rejects_unvalidated_private_identity_payload(
    tmp_path: Path,
) -> None:
    report = tmp_path / SUCCESSOR_TERMINAL_ASSURANCE_REPORT_NAME
    report.write_bytes(b'{"kind":"private_parser_input_generation"}\n')
    (tmp_path / "data.bin").write_bytes(b"public")

    with pytest.raises(ValueError, match="private parser-input sentinel"):
        assert_no_private_capture_sentinels(tmp_path)

    with pytest.raises(ValueError, match="not canonical assurance"):
        assert_no_private_capture_sentinels(
            tmp_path,
            sentinel_excluded_paths=frozenset({SUCCESSOR_TERMINAL_ASSURANCE_REPORT_NAME}),
        )

    with pytest.raises(ValueError, match="unsupported public control"):
        assert_no_private_capture_sentinels(
            tmp_path,
            sentinel_excluded_paths=frozenset({"data.bin"}),
        )


def test_public_artifact_rejects_a_real_private_capture_store_layout(
    tmp_path: Path,
) -> None:
    public_root = tmp_path / "public"
    public_root.mkdir()
    with (
        BronzeCaptureStore(
            tmp_path / "private",
            limits=BronzeLimits(
                max_response_bytes=1_000,
                max_generation_stored_bytes=10_000,
                minimum_free_bytes=1,
                max_receipt_bytes=1_000,
                max_receipt_count=10,
            ),
            public_roots=[public_root],
        ) as store,
        pytest.raises(ValueError, match="private parser-input layout path"),
    ):
        assert_no_private_capture_sentinels(store.root)


@pytest.mark.parametrize(
    "relative_path",
    [
        "blobs/sha256/aa/" + "a" * 64 + ".payload.gz",
        "receipts/attempts/bb/" + "b" * 64 + ".json",
        "receipts/calls/cc/" + "c" * 64 + ".json",
    ],
)
def test_public_artifact_rejects_private_capture_layout_signatures(
    tmp_path: Path,
    relative_path: str,
) -> None:
    target = tmp_path / relative_path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"opaque-private-bytes")

    with pytest.raises(ValueError, match="private parser-input layout path"):
        assert_no_private_capture_sentinels(tmp_path)


@pytest.mark.parametrize("kind", ["response_attempt", "logical_call"])
def test_public_artifact_rejects_renamed_private_receipt_json(
    tmp_path: Path,
    kind: str,
) -> None:
    (tmp_path / "renamed-public-looking.bin").write_text(
        json.dumps({"schema_version": 5, "kind": kind}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="private parser-input"):
        assert_no_private_capture_sentinels(tmp_path)


@pytest.mark.parametrize("kind", ["response_attempt", "logical_call"])
def test_public_artifact_rejects_large_whitespace_private_receipt(
    tmp_path: Path,
    kind: str,
) -> None:
    target = tmp_path / "large-public-looking.bin"
    padding = b" " * (2 * 1024 * 1024 + 17)
    target.write_bytes(b'{"kind"' + padding + b":" + padding + b'"' + kind.encode() + b'"}')

    with pytest.raises(ValueError, match="private parser-input sentinel"):
        assert_no_private_capture_sentinels(tmp_path)


@pytest.mark.parametrize("kind", ["response_attempt", "logical_call"])
def test_public_artifact_rejects_renamed_whitespace_private_gzip(
    tmp_path: Path,
    kind: str,
) -> None:
    payload = b'{\n\t"kind" \r\n:\t "' + kind.encode() + b'"\n}'
    (tmp_path / "public-looking-cache.bin").write_bytes(
        gzip.compress(payload, compresslevel=6, mtime=0)
    )

    with pytest.raises(ValueError, match="private parser-input sentinel"):
        assert_no_private_capture_sentinels(tmp_path)


def test_public_artifact_rejects_private_payload_suffix_in_any_directory(
    tmp_path: Path,
) -> None:
    target = tmp_path / "exports" / "renamed.payload.gz"
    target.parent.mkdir()
    target.write_bytes(gzip.compress(b"otherwise opaque", mtime=0))

    with pytest.raises(ValueError, match="private parser-input layout path"):
        assert_no_private_capture_sentinels(tmp_path)


def test_public_artifact_allows_legitimate_gzip_without_private_evidence(
    tmp_path: Path,
) -> None:
    (tmp_path / "legitimate-public-export.gz").write_bytes(
        gzip.compress(b'{"kind":"public_export","rows":42}', mtime=0)
    )

    assert_no_private_capture_sentinels(tmp_path)


def test_public_artifact_rejects_malformed_gzip_with_private_structure(
    tmp_path: Path,
) -> None:
    payload = b'{"kind":' + b" " * (artifact_identity._PRIVATE_GZIP_READ_BYTES * 2)
    compressed = gzip.compress(payload, mtime=0)
    (tmp_path / "truncated-public-looking.bin").write_bytes(compressed[:-8])

    with pytest.raises(ValueError, match="malformed or incomplete gzip"):
        assert_no_private_capture_sentinels(tmp_path)


def test_private_gzip_inspection_limit_fails_closed_for_every_unfinished_stream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(artifact_identity, "_MAX_PRIVATE_GZIP_DECOMPRESSED_BYTES", 64)
    monkeypatch.setattr(artifact_identity, "_MIN_PRIVATE_GZIP_DECOMPRESSED_BYTES", 64)
    monkeypatch.setattr(artifact_identity, "_MAX_PRIVATE_GZIP_EXPANSION_RATIO", 1)

    ordinary_root = tmp_path / "ordinary"
    ordinary_root.mkdir()
    (ordinary_root / "ordinary.gz").write_bytes(gzip.compress(b"x" * 4_096, mtime=0))
    with pytest.raises(ValueError, match="cannot be fully inspected"):
        assert_no_private_capture_sentinels(ordinary_root)

    suspicious_root = tmp_path / "suspicious"
    suspicious_root.mkdir()
    suspicious_payload = b'{"kind":' + b" " * 4_096 + b'"logical_call"}'
    (suspicious_root / "renamed.bin").write_bytes(gzip.compress(suspicious_payload, mtime=0))
    with pytest.raises(ValueError, match="cannot be fully inspected"):
        assert_no_private_capture_sentinels(suspicious_root)


def test_private_marker_starting_after_gzip_cap_is_not_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(artifact_identity, "_MAX_PRIVATE_GZIP_DECOMPRESSED_BYTES", 64)
    monkeypatch.setattr(artifact_identity, "_MIN_PRIVATE_GZIP_DECOMPRESSED_BYTES", 64)
    monkeypatch.setattr(artifact_identity, "_MAX_PRIVATE_GZIP_EXPANSION_RATIO", 1)
    payload = b" " * 65 + b'{"kind":"logical_call"}'
    (tmp_path / "public-looking.bin").write_bytes(gzip.compress(payload, mtime=0))

    with pytest.raises(ValueError, match="cannot be fully inspected"):
        assert_no_private_capture_sentinels(tmp_path)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires POSIX FIFOs")
def test_public_artifact_rejects_special_file_without_reading_it(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "private-stream")

    with pytest.raises(ValueError, match="not a regular file"):
        assert_no_private_capture_sentinels(tmp_path)


def test_verify_rejects_expected_identity_mismatch(tmp_path: Path) -> None:
    _write_artifact(tmp_path)
    build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )

    with pytest.raises(ValueError, match="source_sha mismatch"):
        verify_assured_artifact_manifest(tmp_path, expected_source_sha="c" * 40)


def test_metadata_created_after_manifest_is_not_part_of_data_identity(tmp_path: Path) -> None:
    _write_artifact(tmp_path)
    build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )
    (tmp_path / "dataset-metadata.json").write_text("{}\n", encoding="utf-8")

    manifest = verify_assured_artifact_manifest(tmp_path)

    assert all(entry["path"] != "dataset-metadata.json" for entry in manifest["files"])


def test_verify_rejects_manifest_with_inconsistent_tree_fingerprint(tmp_path: Path) -> None:
    _write_artifact(tmp_path)
    manifest_path = build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["data_tree_fingerprint"] = "d" * 64
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="tree fingerprint is inconsistent"):
        verify_assured_artifact_manifest(tmp_path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("extra_key", "fields are invalid"),
        ("duplicate_key", "cannot be read safely"),
        ("nonfinite", "cannot be read safely"),
        ("noncanonical", "bytes are not canonical"),
        ("trailing_json", "cannot be read safely"),
    ],
)
def test_verify_rejects_noncanonical_or_extended_manifest_authority(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    _write_artifact(tmp_path)
    manifest_path = build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )
    encoded = manifest_path.read_bytes()
    payload = json.loads(encoded)
    if mutation == "extra_key":
        payload["foreign_unvalidated_authority"] = {"value": "foreign"}
        tampered = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    elif mutation == "duplicate_key":
        tampered = b'{\n  "bytes": 0,\n' + encoded[2:]
    elif mutation == "nonfinite":
        tampered = encoded.replace(
            f'"bytes": {payload["bytes"]}'.encode(),
            b'"bytes": NaN',
            1,
        )
    elif mutation == "noncanonical":
        tampered = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    else:
        tampered = encoded + b"{}"
    manifest_path.write_bytes(tampered)

    with pytest.raises(ValueError, match=message):
        verify_assured_artifact_manifest(tmp_path)


def test_verify_rejects_detached_manifest_path(tmp_path: Path) -> None:
    _write_artifact(tmp_path)
    canonical = build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )
    detached = tmp_path.parent / "detached-assured-artifact-manifest.json"
    detached.write_bytes(canonical.read_bytes())

    with pytest.raises(ValueError, match="canonical path"):
        verify_assured_artifact_manifest(tmp_path, manifest_path=detached)


def test_verify_rejects_boolean_schema_version(tmp_path: Path) -> None:
    _write_artifact(tmp_path)
    manifest_path = build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["schema_version"] = True
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported schema"):
        verify_assured_artifact_manifest(tmp_path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("file_count", True, "file count"),
        ("file_count", 1.0, "file count"),
        ("bytes", True, "byte count"),
        ("bytes", 1.0, "byte count"),
    ],
)
def test_verify_rejects_noninteger_aggregate_fields(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    (tmp_path / "one-byte.bin").write_bytes(b"x")
    manifest_path = build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload[field] = value
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        verify_assured_artifact_manifest(tmp_path)


def test_build_atomically_replaces_raced_manifest_symlink_without_following_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_artifact(tmp_path)
    victim = tmp_path.parent / "victim.txt"
    victim.write_text("do not overwrite\n", encoding="utf-8")
    manifest_path = tmp_path / ASSURED_ARTIFACT_MANIFEST_NAME
    original_inventory = artifact_identity._inventory_from_root_descriptor

    def inventory_then_swap(root_descriptor: int) -> list[dict[str, object]]:
        inventory = original_inventory(root_descriptor)
        manifest_path.symlink_to(victim)
        return inventory

    monkeypatch.setattr(
        artifact_identity,
        "_inventory_from_root_descriptor",
        inventory_then_swap,
    )

    build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )

    assert victim.read_text(encoding="utf-8") == "do not overwrite\n"
    assert manifest_path.is_file()
    assert not manifest_path.is_symlink()


def test_verify_rejects_manifest_symlink_without_following_it(tmp_path: Path) -> None:
    _write_artifact(tmp_path)
    manifest_path = build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )
    detached = tmp_path.parent / "valid-detached-manifest.json"
    detached.write_bytes(manifest_path.read_bytes())
    manifest_path.unlink()
    manifest_path.symlink_to(detached)

    with pytest.raises(ValueError, match="symlinks"):
        verify_assured_artifact_manifest(tmp_path)


def test_inventory_rejects_nested_directory_symlink(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside"
    outside.mkdir()
    (outside / "outside.bin").write_bytes(b"outside")
    (tmp_path / "inside.bin").write_bytes(b"inside")
    (tmp_path / "nested").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlinks"):
        build_assured_artifact_manifest(
            tmp_path,
            chain_id="full-20260711",
            source_sha=_SOURCE_SHA,
            coverage_fingerprint=_COVERAGE_FINGERPRINT,
        )


def test_nested_inventory_is_globally_sorted_before_manifest_creation(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "child.bin").write_bytes(b"child")
    (tmp_path / "a.txt").write_bytes(b"sibling")

    build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )
    manifest = verify_assured_artifact_manifest(tmp_path)

    assert [entry["path"] for entry in manifest["files"]] == ["a.txt", "a/child.bin"]


def test_verify_cli_prints_bounded_summary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_artifact(tmp_path)
    build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )

    assert (
        main(
            [
                "verify",
                "--root",
                str(tmp_path),
                "--chain-id",
                "full-20260711",
                "--source-sha",
                _SOURCE_SHA,
                "--coverage-fingerprint",
                _COVERAGE_FINGERPRINT,
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "verified"
    assert output["file_count"] == 2
    assert "files" not in output
