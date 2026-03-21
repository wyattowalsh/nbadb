from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactDefenseHubTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_defense_hub"
    depends_on: ClassVar[list[str]] = ["stg_defense_hub"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_defense_hub
    """
