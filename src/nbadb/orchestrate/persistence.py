from __future__ import annotations

import json
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def atomic_write_path(path: Path, writer: Callable[[Path], None]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    try:
        writer(temp_path)
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def atomic_write_text(path: Path, content: str) -> None:
    atomic_write_path(path, lambda temp_path: temp_path.write_text(content, encoding="utf-8"))


def read_json_object(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("ignoring unreadable JSON metadata {}: {}", path, type(exc).__name__)
        return {}
    if not isinstance(payload, dict):
        logger.warning("ignoring non-object JSON metadata {}", path)
        return {}
    return payload
