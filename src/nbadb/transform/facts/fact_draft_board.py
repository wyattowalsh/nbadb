from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactDraftBoardTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_draft_board"
    depends_on: ClassVar[list[str]] = ["stg_draft_board"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_draft_board
    """
