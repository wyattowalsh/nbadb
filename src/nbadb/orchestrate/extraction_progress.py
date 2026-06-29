from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from nbadb.orchestrate.planning import ExtractionPlanItem

from nbadb.orchestrate.persistence import atomic_write_text, read_json_object


@dataclass(frozen=True, slots=True)
class ExtractionSliceKey:
    run_mode: str
    label: str
    pattern: str
    scope_hash: str

    @property
    def slug(self) -> str:
        safe_label = self.label.lower().replace("/", "-").replace(" ", "-")
        safe_label = "".join(ch for ch in safe_label if ch.isalnum() or ch in {"-", "_"})
        return f"{self.run_mode}.{self.pattern}.{safe_label[:48]}.{self.scope_hash}"


class ExtractionProgressStore:
    SCHEMA_VERSION = 2

    def __init__(self, root_dir: Path | None) -> None:
        self._root_dir = root_dir

    @classmethod
    def from_duckdb_path(cls, duckdb_path: Path | None) -> ExtractionProgressStore:
        if duckdb_path is None:
            return cls(None)
        return cls(duckdb_path.with_name(f"{duckdb_path.stem}.extraction-progress"))

    def is_available(self) -> bool:
        return self._root_dir is not None

    def slice_key(self, run_mode: str, item: ExtractionPlanItem) -> ExtractionSliceKey:
        payload = json.dumps(
            {
                "pattern": item.pattern,
                "label": item.label,
                "entries": [entry.endpoint_name for entry in item.entries],
                "params": item.params,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        scope_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        return ExtractionSliceKey(
            run_mode=run_mode,
            label=item.label,
            pattern=item.pattern,
            scope_hash=scope_hash,
        )

    def is_complete(self, key: ExtractionSliceKey) -> bool:
        payload = self.load(key)
        if not payload or str(payload.get("status", "")) != "complete":
            return False
        if int(payload.get("schema_version", 0) or 0) != self.SCHEMA_VERSION:
            return False
        failure_count = int(payload.get("failure_count", 0) or 0)
        retry_skip_count = int(payload.get("retry_skip_count", 0) or 0)
        deferred_failure_count = int(payload.get("deferred_failure_count", 0) or 0)
        if failure_count or deferred_failure_count:
            return False
        eligible_calls = int(payload.get("eligible_calls", -1) or 0)
        success_count = int(payload.get("success_count", -1) or 0)
        journal_skip_count = int(payload.get("journal_skip_count", 0) or 0)
        completed = success_count + journal_skip_count + retry_skip_count
        return eligible_calls >= 0 and completed == eligible_calls

    def load(self, key: ExtractionSliceKey) -> dict[str, Any]:
        if not self.is_available():
            return {}
        path = self._path(key)
        return read_json_object(
            path,
            metadata_label="extraction progress metadata",
        )

    def mark_started(self, key: ExtractionSliceKey, *, task_count: int) -> None:
        self._write(
            key,
            {
                "schema_version": self.SCHEMA_VERSION,
                "status": "running",
                "task_count": task_count,
                "started_at": datetime.now(UTC).isoformat(),
            },
        )

    def mark_complete(
        self,
        key: ExtractionSliceKey,
        *,
        task_count: int,
        row_count: int,
        wall_time_seconds: float,
        staging_keys: list[str],
        endpoint_families: list[str],
        eligible_calls: int | None = None,
        success_count: int | None = None,
        journal_skip_count: int = 0,
        retry_skip_count: int = 0,
        support_skip_count: int = 0,
        failure_count: int = 0,
        deferred_failure_count: int = 0,
    ) -> None:
        resolved_eligible_calls = task_count if eligible_calls is None else eligible_calls
        resolved_success_count = resolved_eligible_calls if success_count is None else success_count
        self._write(
            key,
            {
                "schema_version": self.SCHEMA_VERSION,
                "status": "complete",
                "task_count": task_count,
                "eligible_calls": resolved_eligible_calls,
                "success_count": resolved_success_count,
                "journal_skip_count": journal_skip_count,
                "retry_skip_count": retry_skip_count,
                "support_skip_count": support_skip_count,
                "failure_count": failure_count,
                "deferred_failure_count": deferred_failure_count,
                "row_count": row_count,
                "wall_time_seconds": wall_time_seconds,
                "staging_keys": staging_keys,
                "endpoint_families": endpoint_families,
                "completed_at": datetime.now(UTC).isoformat(),
            },
        )

    def mark_failed(
        self,
        key: ExtractionSliceKey,
        *,
        task_count: int,
        error: str,
        eligible_calls: int = 0,
        success_count: int = 0,
        journal_skip_count: int = 0,
        retry_skip_count: int = 0,
        support_skip_count: int = 0,
        failure_count: int = 0,
        deferred_failure_count: int = 0,
    ) -> None:
        self._write(
            key,
            {
                "schema_version": self.SCHEMA_VERSION,
                "status": "failed",
                "task_count": task_count,
                "eligible_calls": eligible_calls,
                "success_count": success_count,
                "journal_skip_count": journal_skip_count,
                "retry_skip_count": retry_skip_count,
                "support_skip_count": support_skip_count,
                "failure_count": failure_count,
                "deferred_failure_count": deferred_failure_count,
                "error": error,
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )

    def _write(self, key: ExtractionSliceKey, payload: dict[str, Any]) -> None:
        if not self.is_available():
            return
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {
            "run_mode": key.run_mode,
            "label": key.label,
            "pattern": key.pattern,
            "scope_hash": key.scope_hash,
            **payload,
        }
        atomic_write_text(path, json.dumps(body, indent=2) + "\n")

    def _path(self, key: ExtractionSliceKey) -> Path:
        root_dir = self._root_dir
        assert root_dir is not None
        return root_dir / f"{key.slug}.json"
