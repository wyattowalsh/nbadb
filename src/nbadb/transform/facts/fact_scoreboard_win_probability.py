from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactScoreboardWinProbabilityTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_scoreboard_win_probability"
    depends_on: ClassVar[list[str]] = ["stg_scoreboard_win_probability"]

    _SQL: ClassVar[str] = """SELECT * FROM stg_scoreboard_win_probability"""
