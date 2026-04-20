from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class BridgeGameOfficialTransformer(SqlTransformer):
    output_table: ClassVar[str] = "bridge_game_official"
    depends_on: ClassVar[list[str]] = ["stg_officials"]

    _SQL: ClassVar[str] = """
        SELECT DISTINCT game_id, official_id
        FROM stg_officials
    """
