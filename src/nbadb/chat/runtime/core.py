from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nbadb.agent.query import QueryAgent
from nbadb.chat.artifacts import ArtifactStore
from nbadb.chat.memory import FindingRecord, MemoryStore
from nbadb.core.config import get_settings

if TYPE_CHECKING:
    from pathlib import Path

    from nbadb.chat.sql import QueryResponse


@dataclass(frozen=True)
class ChatRuntime:
    duckdb_path: Path
    memory_store: MemoryStore = field(default_factory=MemoryStore)
    artifact_store: ArtifactStore = field(default_factory=ArtifactStore)

    def ask(self, question: str, *, limit: int = 10) -> QueryResponse:
        return QueryAgent(self.duckdb_path).ask_result(question, limit=limit)

    def promote_to_finding(
        self,
        response: QueryResponse,
        *,
        title: str,
        summary: str = "",
        session_id: str | None = None,
    ) -> FindingRecord:
        metadata = dict(response.metadata)
        metadata.update(
            {
                "route": response.route,
                "tables": list(response.tables),
                "row_count": response.row_count,
                "session_id": session_id,
            }
        )
        if response.sql:
            metadata.setdefault("sql", response.sql)
        record = FindingRecord(
            title=title,
            summary=summary or response.render_text(),
            metadata=metadata,
            entities=tuple(response.tables),
            session_id=session_id,
        )
        self.artifact_store.save_finding(
            title=record.title,
            summary=record.summary,
            metadata={
                **metadata,
                "finding": record.model_dump(),
            },
        )
        return record


def build_runtime() -> ChatRuntime:
    settings = get_settings()
    duckdb_path = settings.duckdb_path
    if duckdb_path is None:
        raise RuntimeError("NBADB_DUCKDB_PATH is not configured")
    return ChatRuntime(duckdb_path=duckdb_path)
