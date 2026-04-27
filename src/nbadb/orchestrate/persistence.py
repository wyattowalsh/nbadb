from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Callable


def atomic_write_path(path: Path, writer: Callable[[Path], None]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        writer(temp_path)
        _fsync_file(temp_path)
        temp_path.replace(path)
        _fsync_directory(path.parent)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def atomic_write_text(path: Path, content: str) -> None:
    atomic_write_path(path, lambda temp_path: temp_path.write_text(content, encoding="utf-8"))


def read_json_object(path: Path, *, metadata_label: str = "JSON metadata") -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "ignoring unreadable {} {}: {}",
            metadata_label,
            path,
            type(exc).__name__,
        )
        _quarantine_corrupt_path(path, reason=type(exc).__name__, metadata_label=metadata_label)
        return {}
    if not isinstance(payload, dict):
        logger.warning("ignoring non-object {} {}", metadata_label, path)
        _quarantine_corrupt_path(path, reason=type(payload).__name__, metadata_label=metadata_label)
        return {}
    return payload


def _fsync_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        with path.open("rb") as handle:
            os.fsync(handle.fileno())
    except OSError as exc:
        logger.debug("skipping file fsync for {}: {}", path, type(exc).__name__)


def _fsync_directory(path: Path) -> None:
    try:
        directory_fd = os.open(path, os.O_RDONLY)
    except OSError as exc:
        logger.debug("skipping directory fsync for {}: {}", path, type(exc).__name__)
        return
    try:
        os.fsync(directory_fd)
    except OSError as exc:
        logger.debug("skipping directory fsync for {}: {}", path, type(exc).__name__)
    finally:
        os.close(directory_fd)


def _quarantine_corrupt_path(path: Path, *, reason: str, metadata_label: str) -> None:
    if not path.exists():
        return
    quarantine_path = path.with_name(f"{path.name}.corrupt.{reason}")
    suffix = 0
    while quarantine_path.exists():
        suffix += 1
        quarantine_path = path.with_name(f"{path.name}.corrupt.{reason}.{suffix}")
    try:
        path.replace(quarantine_path)
    except OSError as exc:
        logger.warning(
            "failed to quarantine unreadable {} {}: {}",
            metadata_label,
            path,
            type(exc).__name__,
        )
        return
    logger.warning(
        "quarantined unreadable {} {} -> {}",
        metadata_label,
        path,
        quarantine_path,
    )
