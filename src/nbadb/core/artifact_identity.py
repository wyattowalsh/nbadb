from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import secrets
import stat
from contextlib import contextmanager, suppress
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Iterator

ASSURED_ARTIFACT_MANIFEST_NAME = "assured-artifact-manifest.json"
_EXCLUDED_INVENTORY_NAMES = frozenset(
    {
        ASSURED_ARTIFACT_MANIFEST_NAME,
        "dataset-metadata.json",
    }
)


def _is_lowercase_hex(value: object, *, length: int) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


_OPEN_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_OPEN_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_OPEN_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
_MAX_MANIFEST_BYTES = 64 * 1024 * 1024


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _hash_regular_descriptor(descriptor: int, *, display_path: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"Assured artifact inventory path is not a regular file: {display_path}")
    while chunk := os.read(descriptor, 1024 * 1024):
        digest.update(chunk)
    after = os.fstat(descriptor)
    if _stat_identity(before) != _stat_identity(after):
        raise ValueError(f"Assured artifact file changed while hashing: {display_path}")
    return before.st_size, digest.hexdigest()


def _open_child_descriptor(parent_descriptor: int, name: str, *, display_path: str) -> int:
    if not _OPEN_NOFOLLOW:
        raise RuntimeError("Assured artifact identity requires O_NOFOLLOW support")
    flags = os.O_RDONLY | _OPEN_NOFOLLOW | _OPEN_CLOEXEC | _OPEN_NONBLOCK
    try:
        return os.open(name, flags, dir_fd=parent_descriptor)
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.EMLINK}:
            raise ValueError(f"Assured artifact must not contain symlinks: {display_path}") from exc
        raise ValueError(f"Assured artifact changed while opening: {display_path}") from exc


def _inventory_from_descriptor(
    directory_descriptor: int,
    *,
    prefix: PurePosixPath | None = None,
) -> list[dict[str, Any]]:
    try:
        with os.scandir(directory_descriptor) as iterator:
            names = sorted(entry.name for entry in iterator)
    except OSError as exc:
        display_path = prefix.as_posix() if prefix is not None else "."
        raise ValueError(
            f"Assured artifact directory cannot be inventoried: {display_path}"
        ) from exc

    files: list[dict[str, Any]] = []
    for name in names:
        relative = PurePosixPath(name) if prefix is None else prefix / name
        relative_path = relative.as_posix()
        descriptor = _open_child_descriptor(
            directory_descriptor,
            name,
            display_path=relative_path,
        )
        try:
            mode = os.fstat(descriptor).st_mode
            if stat.S_ISDIR(mode):
                files.extend(_inventory_from_descriptor(descriptor, prefix=relative))
                continue
            if relative_path in _EXCLUDED_INVENTORY_NAMES:
                if not stat.S_ISREG(mode):
                    raise ValueError(
                        "Assured artifact excluded inventory path is not a regular file: "
                        f"{relative_path}"
                    )
                continue
            byte_count, sha256 = _hash_regular_descriptor(
                descriptor,
                display_path=relative_path,
            )
            files.append(
                {
                    "path": relative_path,
                    "bytes": byte_count,
                    "sha256": sha256,
                }
            )
        finally:
            os.close(descriptor)
    return files


@contextmanager
def _open_artifact_root(root: Path) -> Iterator[tuple[Path, int]]:
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise NotADirectoryError(f"Assured artifact root is not a directory: {root}") from exc
    if not _OPEN_NOFOLLOW:
        raise RuntimeError("Assured artifact identity requires O_NOFOLLOW support")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | _OPEN_NOFOLLOW
        | _OPEN_CLOEXEC
        | _OPEN_NONBLOCK
    )
    try:
        descriptor = os.open(resolved_root, flags)
    except OSError as exc:
        raise NotADirectoryError(f"Assured artifact root is not a directory: {root}") from exc
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise NotADirectoryError(f"Assured artifact root is not a directory: {root}")
        yield resolved_root, descriptor
    finally:
        os.close(descriptor)


def _inventory_from_root_descriptor(root_descriptor: int) -> list[dict[str, Any]]:
    files = _inventory_from_descriptor(root_descriptor)
    if not files:
        raise ValueError("Assured artifact inventory is empty")
    files.sort(key=lambda item: item["path"])
    return files


def _canonical_manifest_path(resolved_root: Path, manifest_path: Path | None) -> Path:
    canonical = resolved_root / ASSURED_ARTIFACT_MANIFEST_NAME
    requested = manifest_path or canonical
    if Path(os.path.abspath(requested)) != canonical:
        raise ValueError("Assured artifact manifest must use the canonical path inside its root")
    return canonical


def _atomic_write_manifest(root_descriptor: int, payload: bytes) -> None:
    temporary_name = f".{ASSURED_ARTIFACT_MANIFEST_NAME}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _OPEN_NOFOLLOW | _OPEN_CLOEXEC
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary_name, flags, 0o600, dir_fd=root_descriptor)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write while creating assured artifact manifest")
            view = view[written:]
        os.fchmod(descriptor, 0o644)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(
            temporary_name,
            ASSURED_ARTIFACT_MANIFEST_NAME,
            src_dir_fd=root_descriptor,
            dst_dir_fd=root_descriptor,
        )
        os.fsync(root_descriptor)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        with suppress(FileNotFoundError):
            os.unlink(temporary_name, dir_fd=root_descriptor)


def _read_manifest(root_descriptor: int) -> object:
    descriptor = _open_child_descriptor(
        root_descriptor,
        ASSURED_ARTIFACT_MANIFEST_NAME,
        display_path=ASSURED_ARTIFACT_MANIFEST_NAME,
    )
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("Assured artifact manifest is not a regular file")
        if before.st_size > _MAX_MANIFEST_BYTES:
            raise ValueError("Assured artifact manifest exceeds the safe size limit")
        chunks: list[bytes] = []
        total_bytes = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            total_bytes += len(chunk)
            if total_bytes > _MAX_MANIFEST_BYTES:
                raise ValueError("Assured artifact manifest exceeds the safe size limit")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if _stat_identity(before) != _stat_identity(after):
            raise ValueError("Assured artifact manifest changed while reading")
    finally:
        os.close(descriptor)
    try:
        return json.loads(b"".join(chunks))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Assured artifact manifest cannot be read safely") from exc


def _tree_fingerprint(files: list[dict[str, Any]]) -> str:
    source = json.dumps(files, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _validate_manifest_payload(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Assured artifact manifest has an unsupported schema")
    payload_dict = cast("dict[str, Any]", payload)
    schema_version = payload_dict.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        raise ValueError("Assured artifact manifest has an unsupported schema")
    chain_id = payload_dict.get("chain_id")
    if not isinstance(chain_id, str) or not chain_id.strip():
        raise ValueError("Assured artifact manifest chain_id must be nonempty")
    if not _is_lowercase_hex(payload_dict.get("source_sha"), length=40):
        raise ValueError("Assured artifact manifest source_sha must be 40 lowercase hex characters")
    if not _is_lowercase_hex(payload_dict.get("coverage_fingerprint"), length=64):
        raise ValueError(
            "Assured artifact manifest coverage_fingerprint must be 64 lowercase hex characters"
        )
    if not _is_lowercase_hex(payload_dict.get("data_tree_fingerprint"), length=64):
        raise ValueError(
            "Assured artifact manifest data_tree_fingerprint must be 64 lowercase hex characters"
        )

    files = payload_dict.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("Assured artifact manifest files must be a nonempty list")
    normalized_files: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for raw_file in files:
        if not isinstance(raw_file, dict):
            raise ValueError("Assured artifact manifest file entries must be objects")
        raw_file_dict = cast("dict[str, Any]", raw_file)
        relative_path = raw_file_dict.get("path")
        if not isinstance(relative_path, str):
            raise ValueError("Assured artifact manifest contains an invalid or duplicate path")
        pure_path = PurePosixPath(relative_path)
        if (
            pure_path.is_absolute()
            or not pure_path.parts
            or ".." in pure_path.parts
            or relative_path in seen_paths
            or relative_path in _EXCLUDED_INVENTORY_NAMES
        ):
            raise ValueError("Assured artifact manifest contains an invalid or duplicate path")
        byte_count = raw_file_dict.get("bytes")
        if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count < 0:
            raise ValueError("Assured artifact manifest file bytes must be nonnegative integers")
        if not _is_lowercase_hex(raw_file_dict.get("sha256"), length=64):
            raise ValueError("Assured artifact manifest file sha256 must be lowercase hex")
        seen_paths.add(relative_path)
        normalized_files.append(
            {
                "path": relative_path,
                "bytes": byte_count,
                "sha256": raw_file_dict["sha256"],
            }
        )
    normalized_files.sort(key=lambda item: item["path"])
    if normalized_files != files:
        raise ValueError("Assured artifact manifest files must be sorted by path")
    file_count = payload_dict.get("file_count")
    if (
        not isinstance(file_count, int)
        or isinstance(file_count, bool)
        or file_count != len(normalized_files)
    ):
        raise ValueError("Assured artifact manifest file count is inconsistent")
    byte_count = payload_dict.get("bytes")
    if (
        not isinstance(byte_count, int)
        or isinstance(byte_count, bool)
        or byte_count < 0
        or byte_count != sum(item["bytes"] for item in normalized_files)
    ):
        raise ValueError("Assured artifact manifest byte count is inconsistent")
    if _tree_fingerprint(normalized_files) != payload_dict["data_tree_fingerprint"]:
        raise ValueError("Assured artifact manifest tree fingerprint is inconsistent")
    return payload_dict


def build_assured_artifact_manifest(
    root: Path,
    *,
    chain_id: str,
    source_sha: str,
    coverage_fingerprint: str,
    manifest_path: Path | None = None,
) -> Path:
    if not chain_id.strip():
        raise ValueError("chain_id must be nonempty")
    if not _is_lowercase_hex(source_sha, length=40):
        raise ValueError("source_sha must be 40 lowercase hex characters")
    if not _is_lowercase_hex(coverage_fingerprint, length=64):
        raise ValueError("coverage_fingerprint must be 64 lowercase hex characters")

    with _open_artifact_root(root) as (resolved_root, root_descriptor):
        target = _canonical_manifest_path(resolved_root, manifest_path)
        files = _inventory_from_root_descriptor(root_descriptor)
        payload = {
            "schema_version": 1,
            "chain_id": chain_id,
            "source_sha": source_sha,
            "coverage_fingerprint": coverage_fingerprint,
            "data_tree_fingerprint": _tree_fingerprint(files),
            "file_count": len(files),
            "bytes": sum(item["bytes"] for item in files),
            "files": files,
        }
        encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
        _atomic_write_manifest(root_descriptor, encoded)
        return target


def verify_assured_artifact_manifest(
    root: Path,
    *,
    expected_chain_id: str | None = None,
    expected_source_sha: str | None = None,
    expected_coverage_fingerprint: str | None = None,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    with _open_artifact_root(root) as (resolved_root, root_descriptor):
        _canonical_manifest_path(resolved_root, manifest_path)
        manifest = _validate_manifest_payload(_read_manifest(root_descriptor))
        expectations = {
            "chain_id": expected_chain_id,
            "source_sha": expected_source_sha,
            "coverage_fingerprint": expected_coverage_fingerprint,
        }
        for field, expected in expectations.items():
            if expected is not None and manifest[field] != expected:
                raise ValueError(f"Assured artifact manifest {field} mismatch")

        observed_files = _inventory_from_root_descriptor(root_descriptor)
        if observed_files != manifest["files"]:
            raise ValueError("Assured artifact contents do not match the assured inventory")
        return manifest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or verify an assured data artifact manifest"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--root", type=Path, required=True)
    build.add_argument("--chain-id", required=True)
    build.add_argument("--source-sha", required=True)
    build.add_argument("--coverage-fingerprint", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--root", type=Path, required=True)
    verify.add_argument("--chain-id", required=True)
    verify.add_argument("--source-sha", required=True)
    verify.add_argument("--coverage-fingerprint", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "build":
        path = build_assured_artifact_manifest(
            args.root,
            chain_id=args.chain_id,
            source_sha=args.source_sha,
            coverage_fingerprint=args.coverage_fingerprint,
        )
        print(path)
        return 0
    manifest = verify_assured_artifact_manifest(
        args.root,
        expected_chain_id=args.chain_id,
        expected_source_sha=args.source_sha,
        expected_coverage_fingerprint=args.coverage_fingerprint,
    )
    print(
        json.dumps(
            {
                "status": "verified",
                "chain_id": manifest["chain_id"],
                "source_sha": manifest["source_sha"],
                "coverage_fingerprint": manifest["coverage_fingerprint"],
                "data_tree_fingerprint": manifest["data_tree_fingerprint"],
                "file_count": manifest["file_count"],
                "bytes": manifest["bytes"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
