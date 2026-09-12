from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nbadb.core.errors import ResponseContractError
from nbadb.extract.base import BaseExtractor
from nbadb.extract.landing_projection import project_static_landing_frame
from nbadb.extract.nba_api_adapter import fetch_static_packet
from nbadb.extract.registry import registry

if TYPE_CHECKING:
    import polars as pl


@registry.register
class StaticPlayersExtractor(BaseExtractor):
    endpoint_name = "static_players"
    category = "static"

    async def extract(self, **params: Any) -> pl.DataFrame:
        if params:
            raise ResponseContractError("static players snapshot accepts no parameters")
        packet = fetch_static_packet("static_players", capture=self._capture_contract)
        return project_static_landing_frame("static_players", packet.frame)


@registry.register
class StaticWnbaPlayersExtractor(BaseExtractor):
    endpoint_name = "static_wnba_players"
    category = "static"

    async def extract(self, **params: Any) -> pl.DataFrame:
        if params:
            raise ResponseContractError("static WNBA players snapshot accepts no parameters")
        packet = fetch_static_packet("static_wnba_players", capture=self._capture_contract)
        return project_static_landing_frame("static_wnba_players", packet.frame)
