from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerPtShotsDetailTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_pt_shots_detail"
    depends_on: ClassVar[list[str]] = ["stg_player_pt_shots"]

    _SQL: ClassVar[str] = """SELECT * FROM stg_player_pt_shots"""
