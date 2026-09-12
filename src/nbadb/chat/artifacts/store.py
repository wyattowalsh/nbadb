from __future__ import annotations

import json
import re
import secrets
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

_DEFAULT_ROOT = Path.home() / ".nbadb" / "chat" / "artifacts"
_SAFE_STEM_RE = re.compile(r"[^a-z0-9._-]+")
_MAX_TITLE_CHARS = 200
_MAX_SESSION_CHARS = 200
_MAX_SLUG_CHARS = 80
_WRITE_ATTEMPTS = 3
_ARTIFACT_ERROR = "finding could not be stored safely"


class ArtifactStoreError(RuntimeError):
    """A bounded public artifact persistence failure."""


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _slugify(title: str, *, max_chars: int = _MAX_SLUG_CHARS) -> str:
    stem = _SAFE_STEM_RE.sub("-", title.casefold()).strip(".-_")
    bounded = stem[:max_chars].rstrip(".-_")
    return bounded or "untitled"


def _bounded_text(name: str, value: str, *, max_chars: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must be non-empty")
    if len(normalized) > max_chars:
        raise ValueError(f"{name} exceeds {max_chars} character limit")
    return normalized


def _session_bucket(session_id: str) -> str:
    digest = sha256(session_id.encode("utf-8")).hexdigest()
    return f"session-{digest[:32]}"


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
        *,
        session_id: str,
    ) -> dict[str, Any]:
        resolved_title = _bounded_text("finding title", title, max_chars=_MAX_TITLE_CHARS)
        resolved_session = _bounded_text("session_id", session_id, max_chars=_MAX_SESSION_CHARS)
        base_envelope = {
            "title": resolved_title,
            "summary": summary,
            "updated_at": _utc_now(),
            "metadata": metadata or {},
            "session_id": resolved_session,
        }
        try:
            bucket = self._bucket(f"findings/{_session_bucket(resolved_session)}")
            for _ in range(_WRITE_ATTEMPTS):
                nonce = secrets.token_hex(16)
                artifact_id = sha256(
                    f"{resolved_session}\0{resolved_title}\0{nonce}".encode()
                ).hexdigest()[:32]
                path = bucket / f"{_slugify(resolved_title)}-{artifact_id}.json"
                envelope = {**base_envelope, "artifact_id": artifact_id}
                payload = json.dumps(envelope, indent=2, sort_keys=True)
                try:
                    with path.open("x", encoding="utf-8") as handle:
                        handle.write(payload)
                    return envelope
                except FileExistsError:
                    continue
        except (OSError, TypeError, ValueError) as exc:
            raise ArtifactStoreError(_ARTIFACT_ERROR) from exc
        raise ArtifactStoreError(_ARTIFACT_ERROR)

    def search_findings(self, query: str, *, session_id: str) -> list[dict[str, Any]]:
        resolved_session = _bounded_text("session_id", session_id, max_chars=_MAX_SESSION_CHARS)
        if not query.strip():
            return []
        needle = query.casefold()
        hits: list[dict[str, Any]] = []
        try:
            bucket = self._bucket(f"findings/{_session_bucket(resolved_session)}")
            for path in sorted(bucket.glob("*.json")):
                envelope = json.loads(path.read_text(encoding="utf-8"))
                if envelope.get("session_id") != resolved_session:
                    continue
                haystack = f"{envelope.get('title', '')} {envelope.get('summary', '')}".casefold()
                if needle in haystack:
                    hits.append(envelope)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ArtifactStoreError("findings could not be read safely") from exc
        return hits
