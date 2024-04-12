"""
File       : nbadb/nbaDbHelper.py
Author     : @wyattowalsh
Description: Helper module for the NBA database project.
"""
import os
import random
from functools import partial
from json.decoder import JSONDecodeError
from multiprocessing import Pool, cpu_count
from pathlib import Path

import backoff
import pandas as pd
import pandera as pa
import sqlalchemy
from dotenv import load_dotenv
from loguru import logger
from nba_api.stats.endpoints import TeamDetails
from nba_api.stats.static import players, teams
from nbadb.logging import start_logger
from nbadb.schemas import (
    PlayersSchema,
    TeamAwardsChampionshipsSchema,
    TeamAwardsConfSchema,
    TeamAwardsDivSchema,
    TeamBackgroundSchema,
    TeamHistorySchema,
    TeamHofSchema,
    TeamRetiredSchema,
    TeamSocialSitesSchema,
    TeamsSchema,
)
from pyproxyhelper.proxyhelper import ProxyHelper
from requests.exceptions import HTTPError, ProxyError, RequestException, Timeout
from urllib3.exceptions import (
    ConnectionError,
    MaxRetryError,
    ProtocolError,
    ReadTimeoutError,
)

# load the environment variables
load_dotenv()

POOL_SIZE = cpu_count() * 4
PATH_TO_DATA = Path( "nba-db/" )
DB_PATH = PATH_TO_DATA / "nba.sqlite"
TIMEOUT = 3
ENDPOINT_CONSTANTS = {
    "timeout": TIMEOUT,
}


def fatal_code( e ):
    if hasattr( e, "response" ):
        if hasattr( e.response, "status_code" ):
            return 400 <= e.response.status_code < 500


@backoff.on_exception(
    backoff.constant,
    ( ProxyError, RequestException, Timeout, HTTPError, JSONDecodeError,
      ReadTimeoutError, ProtocolError, MaxRetryError, ConnectionError ),
    max_tries=25,
    logger=logger,
    raise_on_giveup=False,
    giveup=fatal_code,
    interval=0,
)
def endpoint_helper( endpoint, proxies, *args, **kwargs ) -> dict:
    """retrieves all available tables as dataframes for a given endpoint with given input args and kwargs.

    Args:
        endpoint (_type_): nba_api endpoint

    Returns:
        dict: all available tables as dataframes
    """
    # friendly log endpoint name, args, and kwargs
    logger.info(
        f'Fetching data for endpoint: {endpoint.__name__} with args: {args} and kwargs: {kwargs}'
    )
    endpoint = endpoint(
        *args,
        **kwargs,
        proxy=random.choice( proxies ),
        **ENDPOINT_CONSTANTS,
    )
    tables = endpoint.get_available_data()
    dfs = endpoint.get_data_frames()
    dfs = { table: df.infer_objects() for table, df in zip( tables, dfs ) }
    logger.info(
        f"Successfully fetched data for endpoint: {endpoint} with {len(dfs)} tables."
    )
    return dfs


class NbaDbHelper:

    def __init__( self ):
        self.conn = self.get_conn()
        self.proxy_helper = ProxyHelper()
        start_logger( console=True, file=True )

    def _check_data_files_exist( self ) -> None:
        # check if the data directory exists
        try:
            os.makedirs( PATH_TO_DATA )
            logger.info( "Data directory created." )
        except FileExistsError:
            pass
        except Exception as e:
            logger.exception( f"Error creating data directory: {e}" )
        # check if the database file exists
        if not os.path.exists( DB_PATH ):
            # create the database file
            try:
                open( DB_PATH, "w" ).close()
                logger.info( "Database file created." )
            except Exception as e:
                logger.exception( f"Error creating database file: {e}" )

    def validate( self, df: pd.DataFrame,
                  schema: pa.DataFrameModel ) -> pd.DataFrame | None:
        try:
            return schema( df, lazy=True )
        except pa.errors.SchemaError as e:
            logger.exception( f"Schema validation error: {e}" )
            return None

    def get_conn( self ) -> sqlalchemy.engine.base.Connection:
        self._check_data_files_exist()
        try:
            conn = sqlalchemy.create_engine( f"sqlite:///{DB_PATH}" )
            return conn
        except Exception as e:
            logger.exception( f"Error connecting to the database: {e}" )

    def write_to_db( self,
                     df: pd.DataFrame,
                     table: str,
                     if_exists: str = "replace" ) -> None:
        try:
            df.to_sql( table, self.conn, if_exists=if_exists, index=False )
            logger.info( f"{table} table updated." )
        except Exception as e:
            logger.exception( f"Error writing {table} table to database: {e}" )

    def get_players( self,
                     return_df: bool = True,
                     write_to_db: bool = True ) -> None | pd.DataFrame:
        """fetches, updates, and -- optionally -- returns the players table

        Args                        :
        return_df ( bool, optional ): whether to return the players DataFrame table. Defaults to False.

             Returns       :
        None | pd.DataFrame: the players table, if return_df is True
        """
        logger.info( "Fetching players data..." )
        # fetch the players data, load as df, and infer data types
        df = pd.DataFrame(
            players.get_players() ).rename( columns={ 'id': "PLAYER_ID" } )
        df.columns = df.columns.str.upper()
        df = self.validate( df, PlayersSchema )
        logger.info( f"Successfully fetched {len(df)} players." )
        if write_to_db:
            self.write_to_db( df, "Players" )
        if return_df:
            return df

    def get_teams( self,
                   return_df: bool = True,
                   write_to_db: bool = True ) -> None | pd.DataFrame:
        """fetches, updates, and -- optionally -- returns the teams table

        Args                        :
        return_df ( bool, optional ): whether to return the teams DataFrame table. Defaults to False.

             Returns       :
        None | pd.DataFrame: the teams table, if return_df is True
        """
        logger.info( "Fetching teams data..." )
        # fetch the teams data, load as df, and infer data types
        teams_df = pd.DataFrame(
            teams.get_teams() ).rename( columns={ 'id': 'TEAM_ID' } )
        teams_df.columns = teams_df.columns.str.upper()
        teams_df = self.validate( teams_df, TeamsSchema )
        logger.info( f"Successfully fetched {len(teams_df)} teams." )
        if write_to_db:
            # write the teams data to the database
            self.write_to_db( teams_df, "Teams" )
        if return_df:
            return teams_df

    def get_team_details( self,
                          return_df: bool = True,
                          write_to_db: bool = True ) -> None | dict:
        logger.info( "Fetching team details..." )
        # load the teams table, filter to get the team IDs, and rename the id column to TEAM_ID
        try:
            teams = pd.read_sql( "Teams",
                                 self.conn )[ 'TEAM_ID' ].astype( str )
            with Pool( len( teams ) ) as pool:
                # fetch the team details for each team ID
                team_details = pool.map(
                    partial( endpoint_helper, TeamDetails,
                             self.proxy_helper.proxies ), teams )
            team_details = [
                team_detail for team_detail in team_details if team_detail
            ]
            # concatenate the team details into a single DataFrame
            team_details_dfs = { k: None for k in team_details[ 0 ].keys() }
            for i, team_detail in enumerate( team_details ):
                for table, df in team_detail.items():
                    if 'TEAM_ID' not in df.columns:
                        df[ 'TEAM_ID' ] = teams[ i ]
                    if team_details_dfs[ table ] is None:
                        team_details_dfs[ table ] = df
                    else:
                        team_details_dfs[ table ] = pd.concat(
                            [ team_details_dfs[ table ], df ],
                            ignore_index=True ).reset_index( drop=True )
            team_details_dfs[ 'TeamBackground' ] = self.validate(
                team_details_dfs[ 'TeamBackground' ], TeamBackgroundSchema )
            team_details_dfs[ 'TeamHistory' ] = self.validate(
                team_details_dfs[ 'TeamHistory' ], TeamHistorySchema )
            team_details_dfs[ 'TeamSocialSites' ] = self.validate(
                team_details_dfs[ 'TeamSocialSites' ], TeamSocialSitesSchema )
            team_details_dfs[ 'TeamAwardsChampionships' ] = self.validate(
                team_details_dfs[ 'TeamAwardsChampionships' ],
                TeamAwardsChampionshipsSchema )
            team_details_dfs[ 'TeamAwardsConf' ] = self.validate(
                team_details_dfs[ 'TeamAwardsConf' ], TeamAwardsConfSchema )
            team_details_dfs[ 'TeamAwardsDiv' ] = self.validate(
                team_details_dfs[ 'TeamAwardsDiv' ], TeamAwardsDivSchema )
            for table in [ 'TeamHof', 'TeamRetired' ]:
                team_details_dfs[ table ] = team_details_dfs[ table ].rename(
                    columns={ 'PLAYERID': 'PLAYER_ID' } )
                team_details_dfs[ table ][ 'PLAYER_ID' ] = team_details_dfs[
                    table ][ 'PLAYER_ID' ].apply( lambda x: str( int(
                        x ) ) if not pd.isna( x ) else str( x ) )
            team_details_dfs[ 'TeamHof' ] = self.validate(
                team_details_dfs[ 'TeamHof' ], TeamHofSchema )
            team_details_dfs[ 'TeamRetired' ] = self.validate(
                team_details_dfs[ 'TeamRetired' ], TeamRetiredSchema )
            logger.info(
                f"Successfully fetched team details for {len(teams)} teams with {len(team_details_dfs)} tables."
            )
            if write_to_db:
                # write the team details data to the database
                for table, df in team_details_dfs.items():
                    self.write_to_db( df, table )
            if return_df:
                return team_details_dfs
        except Exception as e:
            logger.exception( f"Error fetching team details: {e}" )
