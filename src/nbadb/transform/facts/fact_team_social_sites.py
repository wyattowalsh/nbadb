from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactTeamSocialSitesTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_team_social_sites"
    depends_on: ClassVar[list[str]] = ["stg_team_social_sites"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_team_social_sites
    """
