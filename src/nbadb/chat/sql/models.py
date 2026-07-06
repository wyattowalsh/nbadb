from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class QueryResponse:
    question: str
    route: str
    sql: str | None = None
    columns: tuple[str, ...] = ()
    rows: tuple[tuple[Any, ...], ...] = ()
    tables: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    error: str | None = None
    schema_context: str | None = None
    max_rows: int | None = None
    elapsed_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def ok(self) -> bool:
        return self.error is None

    def render_text(self, *, verbose: bool = False) -> str:
        if self.error is not None:
            text = self.error
        elif self.schema_context is not None:
            text = (
                "I couldn't match your question to a known pattern.\n\n"
                "Here is the schema context for a more specific follow-up:\n\n"
                f"{self.schema_context}"
            )
        elif not self.rows:
            text = "No results found."
        else:
            text = self._render_table()

        if not verbose:
            return text

        details: list[str] = [text, "", "Query details:"]
        details.append(f"- route: {self.route}")
        if self.sql:
            details.append("- sql:")
            details.append(f"  {self.sql}")
        if self.tables:
            details.append(f"- tables: {', '.join(self.tables)}")
        if self.max_rows is not None:
            details.append(f"- max_rows: {self.max_rows}")
        if self.elapsed_ms is not None:
            details.append(f"- elapsed_ms: {self.elapsed_ms:.1f}")
        for warning in self.warnings:
            details.append(f"- warning: {warning}")
        return "\n".join(details)

    def _render_table(self) -> str:
        header = " | ".join(self.columns)
        separator = "-+-".join("-" * len(column) for column in self.columns)
        lines = [header, separator]
        for row in self.rows:
            lines.append(" | ".join(str(value) for value in row))
        return "\n".join(lines)
