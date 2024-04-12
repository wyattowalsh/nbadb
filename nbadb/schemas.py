"""
File       : nbadb/schemas.py
Author     : @wyattowalsh
Description: endpoint schema definitions
"""

from pathlib import Path

import pandera as pa


class PlayersSchema( pa.DataFrameModel ):
    PLAYER_ID: str = pa.Field( unique=True,
                               nullable=False,
                               description="unique identifier" )
    FULL_NAME: str = pa.Field( unique=False,
                               nullable=False,
                               description="full name" )
    FIRST_NAME: str = pa.Field( unique=False,
                                nullable=False,
                                description="first name" )
    LAST_NAME: str = pa.Field( unique=False,
                               nullable=False,
                               description="last name" )
    IS_ACTIVE: bool = pa.Field( unique=False,
                                nullable=False,
                                description="active status" )

    class Config:
        name = "Players"
        description = "Players table schema using the players static endpoint"
        add_missing_columns = True
        coerce = True
        strict = True


class TeamsSchema( pa.DataFrameModel ):
    TEAM_ID: str = pa.Field( unique=True,
                             nullable=False,
                             description="unique identifier" )
    FULL_NAME: str = pa.Field( unique=False,
                               nullable=False,
                               description="full name" )
    ABBREVIATION: str = pa.Field( unique=False,
                                  nullable=True,
                                  description="abbreviation" )
    NICKNAME: str = pa.Field( unique=False,
                              nullable=True,
                              description="nickname" )
    CITY: str = pa.Field( unique=False,
                          nullable=True,
                          description="operating city" )
    STATE: str = pa.Field( unique=False,
                           nullable=True,
                           description="operating state" )
    YEAR_FOUNDED: str = pa.Field(
        unique=False,
        nullable=False,
        description="year of establishment",
    )

    class Config:
        name = "Teams"
        description = "Teams table using the Teams static endpoint"
        add_missing_columns = True
        coerce = True
        strict = True


class TeamBackgroundSchema( pa.DataFrameModel ):
    TEAM_ID: str = pa.Field( unique=True,
                             nullable=False,
                             description="unique identifier" )
    ABBREVIATION: str = pa.Field( unique=False,
                                  nullable=True,
                                  description="abbreviation" )
    NICKNAME: str = pa.Field( unique=False,
                              nullable=True,
                              description="nickname" )
    YEARFOUNDED: int = pa.Field(
        unique=False,
        nullable=False,
        description="year of establishment",
    )
    CITY: str = pa.Field( unique=False,
                          nullable=True,
                          description="operating city" )
    ARENA: str = pa.Field( unique=False, nullable=True, description="arena" )
    ARENACAPACITY: float = pa.Field( unique=False,
                                     nullable=True,
                                     description="arena capacity" )
    OWNER: str = pa.Field( unique=False, nullable=True, description="owner" )
    GENERALMANAGER: str = pa.Field( unique=False,
                                    nullable=True,
                                    description="general manager" )
    HEADCOACH: str = pa.Field( unique=False,
                               nullable=True,
                               description="head coach" )
    DLEAGUEAFFILIATION: str = pa.Field( unique=False,
                                        nullable=True,
                                        description="D-League affiliation" )

    class Config:
        name = "TeamBackground"
        description = "Team background table using the TeamDetails static endpoint"
        add_missing_columns = True
        coerce = True
        strict = True


class TeamHistorySchema( pa.DataFrameModel ):
    TEAM_ID: str = pa.Field( unique=False,
                             nullable=False,
                             description="unique identifier" )
    CITY: str = pa.Field( unique=False,
                          nullable=True,
                          description="operating city" )
    NICKNAME: str = pa.Field( unique=False,
                              nullable=True,
                              description="nickname" )
    YEARFOUNDED: int = pa.Field(
        unique=False,
        nullable=False,
        description="year of establishment",
    )
    YEARACTIVETILL: int = pa.Field(
        unique=False,
        nullable=False,
        description="year active till",
    )

    class Config:
        name = "TeamHistory"
        description = "Team history table using the TeamDetails static endpoint"
        add_missing_columns = True
        coerce = True
        strict = True


class TeamSocialSitesSchema( pa.DataFrameModel ):
    ACCOUNTTYPE: str = pa.Field( unique=False,
                                 nullable=True,
                                 description="account type" )
    WEBSITE_LINK: str = pa.Field( unique=False,
                                  nullable=True,
                                  description="website link" )
    TEAM_ID: str = pa.Field( unique=False,
                             nullable=False,
                             description="unique identifier" )

    class Config:
        name = "TeamSocialSites"
        description = "Team social sites table using the TeamDetails static endpoint"
        add_missing_columns = True
        coerce = True
        strict = True


class TeamAwardsChampionshipsSchema( pa.DataFrameModel ):
    YEARAWARDED: int = pa.Field( unique=False,
                                 nullable=False,
                                 description="year awarded" )
    OPPOSITETEAM: str = pa.Field( unique=False,
                                  nullable=True,
                                  description="opposite team" )
    TEAM_ID: str = pa.Field( unique=False,
                             nullable=False,
                             description="unique identifier" )

    class Config:
        name = "TeamAwardsChampionships"
        description = "Team awards and championships table using the TeamDetails static endpoint"
        add_missing_columns = True
        coerce = True
        strict = True


class TeamAwardsConfSchema( pa.DataFrameModel ):
    YEARAWARDED: int = pa.Field( unique=False,
                                 nullable=False,
                                 description="year awarded" )
    OPPOSITETEAM: str = pa.Field( unique=False,
                                  nullable=True,
                                  description="opposite team" )
    TEAM_ID: str = pa.Field( unique=False,
                             nullable=False,
                             description="unique identifier" )

    class Config:
        name = "TeamAwardsConf"
        description = "Team awards and championships table using the TeamDetails static endpoint"
        add_missing_columns = True
        coerce = True
        strict = True


class TeamAwardsDivSchema( pa.DataFrameModel ):
    YEARAWARDED: int = pa.Field( unique=False,
                                 nullable=False,
                                 description="year awarded" )
    OPPOSITETEAM: str = pa.Field( unique=False,
                                  nullable=True,
                                  description="opposite team" )
    TEAM_ID: str = pa.Field( unique=False,
                             nullable=False,
                             description="unique identifier" )

    class Config:
        name = "TeamAwardsDiv"
        description = "Team awards and championships table using the TeamDetails static endpoint"
        add_missing_columns = True
        coerce = True
        strict = True


class TeamHofSchema( pa.DataFrameModel ):
    PLAYER_ID: str = pa.Field( unique=False,
                               nullable=False,
                               description="unique identifier" )
    PLAYER: str = pa.Field( unique=False, nullable=True, description="player" )
    POSITION: str = pa.Field( unique=False,
                              nullable=True,
                              description="position" )
    JERSEY: str = pa.Field( unique=False, nullable=True, description="jersey" )
    SEASONSWITHTEAM: str = pa.Field( unique=False,
                                     nullable=True,
                                     description="seasons with team" )
    YEAR: str = pa.Field( unique=False, nullable=True, description="year" )
    TEAM_ID: str = pa.Field( unique=False,
                             nullable=False,
                             description="team id" )

    class Config:
        name = "TeamHof"
        description = "Team hall of fame table using the TeamDetails static endpoint"
        add_missing_columns = True
        coerce = True
        strict = True


class TeamRetiredSchema( pa.DataFrameModel ):
    PLAYER_ID: str = pa.Field( unique=False,
                               nullable=False,
                               description="unique identifier" )
    PLAYER: str = pa.Field( unique=False, nullable=True, description="player" )
    POSITION: str = pa.Field( unique=False,
                              nullable=True,
                              description="position" )
    JERSEY: str = pa.Field( unique=False, nullable=True, description="jersey" )
    SEASONSWITHTEAM: str = pa.Field( unique=False,
                                     nullable=True,
                                     description="seasons with team" )
    YEAR: str = pa.Field( unique=False, nullable=True, description="year" )
    TEAM_ID: str = pa.Field( unique=False,
                             nullable=False,
                             description="team id" )

    class Config:
        name = "TeamRetired"
        description = "Team retired table using the TeamDetails static endpoint"
        add_missing_columns = True
        coerce = True
        strict = True


SCHEMAS = [
    PlayersSchema, TeamsSchema, TeamBackgroundSchema, TeamHistorySchema,
    TeamSocialSitesSchema, TeamAwardsChampionshipsSchema, TeamAwardsConfSchema,
    TeamAwardsDivSchema, TeamHofSchema, TeamRetiredSchema
]
SAVE_PATH = Path( "schemas/" )


def save_schemas( schemas: list = SCHEMAS,
                  save_path: Path = SAVE_PATH,
                  yaml_or_json: str = "yaml" ):
    if not save_path.exists():
        save_path.mkdir()
    if yaml_or_json == "yaml":
        for schema in schemas:
            schema.to_yaml( save_path / f"{schema.Config.name}.yaml" )
    elif yaml_or_json == "json":
        for schema in schemas:
            schema.to_json( save_path / f"{schema.Config.name}.json" )
    else:
        raise ValueError( "yaml_or_json must be either 'yaml' or 'json'" )
