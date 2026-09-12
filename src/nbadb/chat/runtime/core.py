from __future__ import annotations

import functools
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb

from nbadb.agent.query import QueryAgent
from nbadb.chat.artifacts import ArtifactStore
from nbadb.chat.memory import FindingRecord, MemoryStore
from nbadb.core.config import get_settings

if TYPE_CHECKING:
    from nbadb.chat.sql import QueryResponse


class WarehouseUnavailableError(RuntimeError):
    """The selected warehouse cannot be safely opened for read-only Q&A."""


_WAREHOUSE_GUIDANCE = (
    "DuckDB warehouse not found or unusable. Set NBADB_DUCKDB_PATH to an existing, "
    "readable, regular DuckDB file."
)


def require_usable_warehouse(duckdb_path: str | Path) -> Path:
    """Return a resolved warehouse path after a side-effect-free DuckDB probe."""
    try:
        path = Path(duckdb_path).expanduser().resolve(strict=True)
        if not path.is_file():
            raise FileNotFoundError
    except (OSError, RuntimeError, ValueError) as exc:
        raise WarehouseUnavailableError(_WAREHOUSE_GUIDANCE) from exc

    try:
        with duckdb.connect(str(path), read_only=True) as connection:
            connection.execute("SET enable_external_access = false")
            connection.execute("SELECT 1").fetchone()
    except (duckdb.Error, OSError) as exc:
        raise WarehouseUnavailableError(_WAREHOUSE_GUIDANCE) from exc
    return path


@dataclass(frozen=True)
class ChatRuntime:
    duckdb_path: Path
    memory_store: MemoryStore = field(default_factory=MemoryStore)
    artifact_store: ArtifactStore = field(default_factory=ArtifactStore)

    @functools.cached_property
    def _query_agent(self) -> QueryAgent:
        """One agent per runtime.

        QueryAgent construction loads and validates the immutable catalog;
        repeating that per message re-runs O(corpus x entries) regex work on
        the event loop. The agent itself opens a fresh read-only DuckDB
        connection per query, so reuse is safe across worker threads.
        """

        return QueryAgent(self.duckdb_path)

    def ask(self, question: str, *, limit: int = 10) -> QueryResponse:
        return self._query_agent.ask_result(question, limit=limit)

    def promote_to_finding(
        self,
        response: QueryResponse,
        *,
        title: str,
        summary: str = "",
        session_id: str,
    ) -> FindingRecord:
        """Persist a finding to the artifact store (durable save path for /save)."""
        if not response.ok:
            raise ValueError("only successful query results can be saved")
        normalized_session_id = session_id.strip()
        if not normalized_session_id:
            raise ValueError("session_id must be non-empty")
        normalized_title = title.strip()
        if not normalized_title:
            raise ValueError("finding title must be non-empty")
        metadata = dict(response.metadata)
        metadata.update(
            {
                "route": response.route,
                "tables": list(response.tables),
                "row_count": response.row_count,
                "session_id": normalized_session_id,
            }
        )
        if response.sql:
            metadata.setdefault("sql", response.sql)
        record = FindingRecord(
            title=normalized_title,
            summary=summary or response.render_text(),
            metadata=metadata,
            entities=tuple(response.tables),
            session_id=normalized_session_id,
        )
        stored = self.artifact_store.save_finding(
            title=record.title,
            summary=record.summary,
            metadata={
                **metadata,
                "finding": record.model_dump(),
            },
            session_id=normalized_session_id,
        )
        return record.model_copy(update={"artifact_bundle_id": stored["artifact_id"]})


def build_runtime() -> ChatRuntime:
    settings = get_settings()
    duckdb_path = settings.duckdb_path
    if duckdb_path is None:
        raise RuntimeError("NBADB_DUCKDB_PATH is not configured")
    path = require_usable_warehouse(duckdb_path)
    return ChatRuntime(duckdb_path=path)
