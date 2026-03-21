from __future__ import annotations

from typing import Any

import polars as pl
from nba_api.stats.static import players as static_players

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry


@registry.register
class StaticPlayersExtractor(BaseExtractor):
    endpoint_name = "static_players"
    category = "static"

    async def extract(self, **params: Any) -> pl.DataFrame:
        data = static_players.get_players()
        return pl.from_records(data)
