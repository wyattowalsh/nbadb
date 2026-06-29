from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_DEFAULT_ROOT = Path.home() / ".nbadb" / "chat" / "artifacts"
_SAFE_STEM_RE = re.compile(r"[^a-z0-9._-]+")


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _slugify(title: str) -> str:
    stem = _SAFE_STEM_RE.sub("-", title.casefold()).strip(".-_")
    return stem or "untitled"


class ArtifactStore:
    def __init__(self, root: Path | None = None) -> None:
        self._root = root or _DEFAULT_ROOT
        self._root.mkdir(parents=True, exist_ok=True)

    def _bucket(self, name: str) -> Path:
        bucket = self._root / name
        bucket.mkdir(parents=True, exist_ok=True)
        return bucket

    def _json_path(self, bucket: str, stem: str) -> Path:
        path = self._bucket(bucket) / f"{_slugify(stem)}.json"
        if path.parent != self._bucket(bucket):
            msg = f"invalid artifact path: {stem!r}"
            raise ValueError(msg)
        return path

    def save_template(
        self,
        name: str,
        payload: dict[str, Any],
        *,
        summary: str = "",
    ) -> dict[str, Any]:
        envelope = {
            "name": name,
            "summary": summary,
            "updated_at": _utc_now(),
            "payload": payload,
        }
        path = self._json_path("templates", name)
        path.write_text(json.dumps(envelope, indent=2, sort_keys=True), encoding="utf-8")
        return envelope

    def load_template(self, name: str) -> dict[str, Any] | None:
        path = self._json_path("templates", name)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def list_templates(self) -> list[str]:
        bucket = self._bucket("templates")
        return sorted(path.stem for path in bucket.glob("*.json"))

    def save_finding(
        self,
        title: str,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        envelope = {
            "title": title,
            "summary": summary,
            "updated_at": _utc_now(),
            "metadata": metadata or {},
        }
        path = self._json_path("findings", title)
        path.write_text(json.dumps(envelope, indent=2, sort_keys=True), encoding="utf-8")
        return envelope

    def search_findings(self, query: str) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        needle = query.casefold()
        hits: list[dict[str, Any]] = []
        for path in sorted(self._bucket("findings").glob("*.json")):
            envelope = json.loads(path.read_text(encoding="utf-8"))
            haystack = f"{envelope.get('title', '')} {envelope.get('summary', '')}".casefold()
            if needle in haystack:
                hits.append(envelope)
        return hits
