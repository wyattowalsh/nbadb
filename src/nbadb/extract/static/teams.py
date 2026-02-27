from __future__ import annotations

from typing import Any

import polars as pl
from nba_api.stats.static import teams as static_teams

from nbadb.extract.base import BaseExtractor


class StaticTeamsExtractor(BaseExtractor):
    endpoint_name = "static_teams"
    category = "static"

    async def extract(self, **params: Any) -> pl.DataFrame:
        data = static_teams.get_teams()
        return pl.from_records(data)
