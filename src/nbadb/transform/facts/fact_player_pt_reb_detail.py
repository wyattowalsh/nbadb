from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerPtRebDetailTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_pt_reb_detail"
    depends_on: ClassVar[list[str]] = ["stg_player_pt_reb"]

    _SQL: ClassVar[str] = """SELECT * FROM stg_player_pt_reb"""
