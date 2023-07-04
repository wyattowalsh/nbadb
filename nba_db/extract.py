"""data extraction functions
"""
# == Imports ========================================================================
import logging
from datetime import datetime
from functools import partial
from multiprocessing import Pool

import numpy as np
import pandas as pd
from nba_api.stats.endpoints.boxscoresummaryv2 import BoxScoreSummaryV2
from nba_api.stats.endpoints.commonplayerinfo import CommonPlayerInfo
from nba_api.stats.endpoints.draftcombinestats import DraftCombineStats
from nba_api.stats.endpoints.drafthistory import DraftHistory
from nba_api.stats.endpoints.leaguegamelog import LeagueGameLog
from nba_api.stats.endpoints.playbyplayv2 import PlayByPlayV2
from nba_api.stats.endpoints.teamdetails import TeamDetails
from nba_api.stats.endpoints.teaminfocommon import TeamInfoCommon
from nba_api.stats.static import players, teams
from pandera.errors import SchemaErrors
from requests.exceptions import RequestException

from nba_db.data import (
    CommonPlayerInfoSchema,
    DraftCombineStatsSchema,
    DraftHistorySchema,
    GameInfoSchema,
    GameSummarySchema,
    InactivePlayersSchema,
    LeagueGameLogSchema,
    LineScoreSchema,
    OfficialsSchema,
    OtherStatsSchema,
    PlayByPlaySchema,
    PlayerSchema,
    TeamDetailsSchema,
    TeamHistorySchema,
    TeamInfoCommonSchema,
    TeamSchema,
)
from nba_db.logger import log

logger = logging.getLogger("nba_db_logger")

# == Constants ======================================================================
season_types = [
    "Regular Season",
    "Pre Season",
    "Playoffs",
    "All-Star",
    "All Star",
    "Preseason",
]


# == Functions ========================================================================
@log(logger)
def get_players(save_to_db: bool = False, conn=None) -> pd.DataFrame:
    """retrieves all players from the static players endpoint

    Args:
        save_to_db (bool, optional): indicator for whether to save result to the database. Defaults to False.
        conn (_type_, optional): SQLAlchemy connection. Defaults to None.

    Returns:
        pd.DataFrame: all players dataframe. None if schema validation fails.
    """
    logger.info("Retrieving all players from the static players endpoint...")
    df = pd.concat(
        [pd.DataFrame(player, index=[0]) for player in players.get_players()],
        ignore_index=True,
    )
    df.columns = df.columns.to_series().apply(lambda x: x.lower())
    try:
        df = PlayerSchema.validate(df, lazy=True)
    except SchemaErrors as err:
        logger.error("Schema validation failed for players")
        logger.error(f"Schema errors: {err.failure_cases}")
        logger.error(f"Invalid dataframe: {err.data}")
        return None
    logger.info("Successfully retrieved all players.")
    if save_to_db:
        logger.info("Saving players to database...")
        df.to_sql("player", conn, if_exists="replace", index=False)
        logger.info("Successfully saved players to database. Returning data...")
    return df


@log(logger)
def get_teams(save_to_db: bool = False, conn=None) -> pd.DataFrame:
    """retrieves all teams from the static teams endpoint

    Args:
        save_to_db (bool, optional): indicator for whether to save result to the database. Defaults to False.
        conn (_type_, optional): SQLAlchemy connection. Defaults to None.

    Returns:
        pd.DataFrame: all teams dataframe. None if schema validation fails.
    """
    logger.info("Retrieving all teams from the static teams endpoint...")
    df = pd.concat(
        [pd.DataFrame(team, index=[0]) for team in teams.get_teams()], ignore_index=True
    )
    df.columns = df.columns.to_series().apply(lambda x: x.lower())
    try:
        df = TeamSchema.validate(df, lazy=True)
    except SchemaErrors as err:
        logger.error("Schema validation failed for players")
        logger.error(f"Schema errors: {err.failure_cases}")
        logger.error(f"Invalid dataframe: {err.data}")
        return None
    logger.info("Successfully retrieved all teams.")
    if save_to_db:
        logger.info("Saving teams to database...")
        df.to_sql("team", conn, if_exists="replace", index=False)
        logger.info("Successfully saved teams to database. Returning data...")
    return df


@log(logger)
def get_league_game_log_from_date(datefrom, proxies, save_to_db=False, conn=None):
    logger.info(f"Retrieving league game log from {datefrom}...")
    dfs = []
    for season_type in season_types:
        while True:
            try:
                df = LeagueGameLog(
                    date_from_nullable=datefrom,
                    proxy=np.random.choice(proxies),
                    season_type_all_star=season_type,
                    timeout=3,
                ).get_data_frames()[0]
                df.columns = df.columns.to_series().apply(lambda x: x.lower())
                df = pd.merge(
                    df,
                    df,
                    on=["season_id", "game_id", "game_date", "min"],
                    suffixes=["_home", "_away"],
                )
                df = df[
                    (df["matchup_home"].str.contains("vs."))
                    & (df["team_name_home"] != df["team_name_away"])
                ]
                df["season_type"] = season_type
                dfs.append(df)
            except RequestException:
                continue
            except ValueError:
                return None
    df = pd.concat(dfs, ignore_index=True)
    try:
        df = LeagueGameLogSchema.validate(df, lazy=True)
    except SchemaErrors as err:
        logger.error("Schema validation failed for league game log")
        logger.error(f"Schema errors: {err.failure_cases}")
        logger.error(f"Invalid dataframe: {err.data}")
        return None
    if save_to_db:
        logger.info("Saving league game log to database...")
        df.to_sql("game", conn, if_exists="append", index=False)
        logger.info("Successfully saved league game log to database. Returning data...")
    return df


def get_league_game_log_all_helper(season, proxies):
    dfs = []
    for season_type in season_types:
        while True:
            try:
                df = LeagueGameLog(
                    season=season,
                    season_type_all_star=season_type,
                    proxy=np.random.choice(proxies),
                    timeout=5,
                ).get_data_frames()[0]
                df.columns = df.columns.to_series().apply(lambda x: x.lower())
                df = pd.merge(
                    df,
                    df,
                    on=["season_id", "game_id", "game_date", "min"],
                    suffixes=["_home", "_away"],
                )
                df = df[
                    (df["matchup_home"].str.contains("vs."))
                    & (df["team_name_home"] != df["team_name_away"])
                ].reset_index(drop=True)
                df["season_type"] = season_type
                dfs.append(df)
                break
            except RequestException:
                continue
            except ValueError:
                break
    df = pd.concat(dfs, ignore_index=True).reset_index(drop=True)
    try:
        df = LeagueGameLogSchema.validate(df, lazy=True)
        return df
    except SchemaErrors as err:
        logger.error("Schema validation failed for league game log")
        logger.error(f"Schema errors: {err.failure_cases}")
        logger.error(f"Invalid dataframe: {err.data}")
        return None


@log(logger)
def get_league_game_log_all(proxies, conn) -> pd.DataFrame:
    """ret

    _extended_summary_

    Returns:
        pd.DataFrame: _description_
    """
    this_year = datetime.now().year
    years = list(range(1946, this_year))
    with Pool(len(years)) as p:
        dfs = p.map(partial(get_league_game_log_all_helper, proxies=proxies), years)
    dfs = [df for df in dfs if df is not None]
    df = pd.concat(dfs, ignore_index=True).reset_index(drop=True)
    df.to_sql("game", conn, if_exists="replace", index=False)
    return df


def get_player_info_helper(player, proxies):
    while True:
        try:
            df = CommonPlayerInfo(
                player_id=player, proxy=np.random.choice(proxies), timeout=3
            ).get_data_frames()[0]
            df.columns = df.columns.to_series().apply(lambda x: x.lower())
            return df
        except RequestException:
            continue
        except ValueError:
            return None


@log(logger)
def get_player_info(proxies, save_to_db: bool = False, conn=None) -> pd.DataFrame:
    player_ids = pd.read_sql("SELECT id FROM player", conn)["id"].astype("category")
    with Pool(250) as p:
        dfs = p.map(partial(get_player_info_helper, proxies=proxies), player_ids)
    dfs = [df for df in dfs if df is not None]
    dfs = pd.concat(dfs, ignore_index=True).reset_index(drop=True)
    try:
        dfs = CommonPlayerInfoSchema.validate(dfs, lazy=True)
    except SchemaErrors as err:
        logger.error("Schema validation failed for players")
        logger.error(f"Schema errors: {err.failure_cases}")
        logger.error(f"Invalid dataframe: {err.data}")
        return None
    logger.info("Successfully retrieved common player info for all players.")
    if save_to_db:
        dfs.to_sql("common_player_info", conn, if_exists="replace", index=False)
    return dfs


def get_teams_details_helper(team, proxies):
    dfs = {"team_details": [], "team_history": []}
    while True:
        try:
            res_dfs = TeamDetails(
                team_id=team, proxy=np.random.choice(proxies), timeout=3
            ).get_data_frames()
            df = pd.concat(
                [
                    res_dfs[0],
                    res_dfs[2].set_index("ACCOUNTTYPE").T.reset_index(drop=True),
                ],
                axis=1,
            )
            df.columns = df.columns.to_series().apply(lambda x: x.lower())
            dfs["team_details"] = df
            history = res_dfs[1]
            history.columns = [
                "team_id",
                "city",
                "nickname",
                "year_founded",
                "year_active_till",
            ]
            history["team_id"] = history["team_id"].astype("category")
            dfs["team_history"] = history
            return dfs
        except RequestException:
            continue
        except ValueError:
            return None


@log(logger)
def get_teams_details(proxies, save_to_db: bool = False, conn=None) -> pd.DataFrame:
    team_ids = pd.read_sql("SELECT id FROM team", conn)["id"].astype("category")
    with Pool(250) as p:
        dfs = p.map(partial(get_teams_details_helper, proxies=proxies), team_ids)
    dfs = [df for df in dfs if df is not None]
    team_details = pd.concat([df["team_details"] for df in dfs], ignore_index=True)
    try:
        team_details = TeamDetailsSchema.validate(team_details, lazy=True)
    except SchemaErrors as err:
        logger.error("Schema validation failed for team details")
        logger.error(f"Schema errors: {err.failure_cases}")
        logger.error(f"Invalid dataframe: {err.data}")
        return None
    team_history = pd.concat([df["team_history"] for df in dfs], ignore_index=True)
    try:
        team_history = TeamHistorySchema.validate(team_history, lazy=True)
    except SchemaErrors as err:
        logger.error("Schema validation failed for team history")
        logger.error(f"Schema errors: {err.failure_cases}")
        logger.error(f"Invalid dataframe: {err.data}")
        return None
    if save_to_db:
        team_details.to_sql("team_details", conn, if_exists="replace", index=False)
        team_history.to_sql("team_history", conn, if_exists="replace", index=False)
    return dfs


def get_box_score_summaries_helper(game_id, proxies):
    dfs = {
        t: []
        for t in [
            "game_summary",
            "other_stats",
            "officials",
            "inactive_players",
            "line_score",
        ]
    }
    while True:
        try:
            res_dfs = BoxScoreSummaryV2(
                game_id=game_id, proxy=np.random.choice(proxies), timeout=3
            ).get_data_frames()
            for df in res_dfs:
                df.columns = df.columns.to_series().apply(lambda x: x.lower())
            df = res_dfs[0].copy()
            try:
                df = GameSummarySchema.validate(df, lazy=True)
            except SchemaErrors as err:
                logger.error("Schema validation failed for league game log")
                logger.error(f"Schema errors: {err.failure_cases}")
                logger.error(f"Invalid dataframe: {err.data}")
                df = None
            dfs["game_summary"] = df
            if len(res_dfs[1]) > 0:
                df = res_dfs[1].copy().assign(game_id=game_id)
                cols = ["game_id"] + df.columns[:-1].tolist()
                df = df[cols]
                df = pd.merge(
                    df,
                    df,
                    on=["league_id", "game_id", "lead_changes", "times_tied"],
                    suffixes=["_home", "_away"],
                )
                df = (
                    df[df["team_id_home"] != df["team_id_away"]]
                    .reset_index(drop=True)
                    .head(1)
                )
                try:
                    df = OtherStatsSchema.validate(df, lazy=True)
                except SchemaErrors as err:
                    logger.error("Schema validation failed for league game log")
                    logger.error(f"Schema errors: {err.failure_cases}")
                    logger.error(f"Invalid dataframe: {err.data}")
                    df = None
            else:
                df = None
            dfs["other_stats"] = df
            df = res_dfs[2].copy().assign(game_id=game_id)
            cols = ["game_id"] + df.columns[:-1].tolist()
            df = df[cols]
            try:
                df = OfficialsSchema.validate(df, lazy=True)
            except SchemaErrors as err:
                logger.error("Schema validation failed for league game log")
                logger.error(f"Schema errors: {err.failure_cases}")
                logger.error(f"Invalid dataframe: {err.data}")
                df = None
            dfs["officials"] = df
            df = res_dfs[3].copy().assign(game_id=game_id)
            cols = ["game_id"] + df.columns[:-1].tolist()
            df = df[cols]
            try:
                df = InactivePlayersSchema.validate(df, lazy=True)
            except SchemaErrors as err:
                logger.error("Schema validation failed for league game log")
                logger.error(f"Schema errors: {err.failure_cases}")
                logger.error(f"Invalid dataframe: {err.data}")
                df = None
            dfs["inactive_players"] = df
            df = res_dfs[4].copy().assign(game_id=game_id)
            cols = ["game_id"] + df.columns[:-1].tolist()
            df = df[cols]
            try:
                df = GameInfoSchema.validate(df, lazy=True)
            except SchemaErrors as err:
                logger.error("Schema validation failed for league game log")
                logger.error(f"Schema errors: {err.failure_cases}")
                logger.error(f"Invalid dataframe: {err.data}")
                df = None
            dfs["game_info"] = df
            df = res_dfs[5].copy()
            df = pd.merge(
                df,
                df,
                on=["game_date_est", "game_sequence", "game_id"],
                suffixes=["_home", "_away"],
            )
            df = (
                df[df["team_id_home"] != df["team_id_away"]]
                .reset_index(drop=True)
                .loc[[0]]
            )
            try:
                df = LineScoreSchema.validate(df, lazy=True)
            except SchemaErrors as err:
                logger.error("Schema validation failed for league game log")
                logger.error(f"Schema errors: {err.failure_cases}")
                logger.error(f"Invalid dataframe: {err.data}")
                df = None
            dfs["line_score"] = df
            return dfs
        except RequestException:
            continue
        except ValueError:
            return None


@log(logger)
def get_box_score_summaries(game_ids, proxies, save_to_db=False, conn=None):
    if len(game_ids) < 250:
        num_workers = len(game_ids)
    else:
        num_workers = 250
    with Pool(num_workers) as p:
        dfs = p.map(partial(get_box_score_summaries_helper, proxies=proxies), game_ids)
    dfs = [d for d in dfs if d is not None]
    game_summary = pd.concat(
        [d["game_summary"] for d in dfs if d["game_summary"] is not None]
    ).reset_index(drop=True)
    other_stats = pd.concat(
        [
            d["other_stats"]
            for d in dfs
            if d["other_stats"] is not None and type(d["other_stats"]) != list
        ]
    ).reset_index(drop=True)
    officials = pd.concat(
        [d["officials"] for d in dfs if d["officials"] is not None]
    ).reset_index(drop=True)
    inactive_players = pd.concat(
        [d["inactive_players"] for d in dfs if d["inactive_players"] is not None]
    ).reset_index(drop=True)
    game_info = pd.concat(
        [d["game_info"] for d in dfs if d["game_info"] is not None]
    ).reset_index(drop=True)
    line_score = pd.concat(
        [d["line_score"] for d in dfs if d["line_score"] is not None]
    ).reset_index(drop=True)
    if save_to_db:
        game_summary.to_sql("game_summary", conn, if_exists="append", index=False)
        other_stats.to_sql("other_stats", conn, if_exists="append", index=False)
        officials.to_sql("officials", conn, if_exists="append", index=False)
        inactive_players.to_sql(
            "inactive_players", conn, if_exists="append", index=False
        )
        game_info.to_sql("game_info", conn, if_exists="append", index=False)
        line_score.to_sql("line_score", conn, if_exists="append", index=False)
    return dfs


def get_play_by_play_helper(game_id, proxies):
    while True:
        try:
            df = PlayByPlayV2(
                game_id=game_id, proxy=np.random.choice(proxies), timeout=3
            ).get_data_frames()[0]
            df.columns = df.columns.to_series().apply(lambda x: x.lower())
            return df
        except RequestException:
            continue
        except ValueError:
            return None


@log(logger)
def get_play_by_play(game_ids, proxies, save_to_db=False, conn=None):
    if len(game_ids) < 250:
        num_workers = len(game_ids)
    else:
        num_workers = 250
    with Pool(num_workers) as p:
        dfs = p.map(partial(get_play_by_play_helper, proxies=proxies), game_ids)
    dfs = pd.concat(dfs).reset_index(drop=True)
    try:
        dfs = PlayByPlaySchema.validate(dfs, lazy=True)
    except SchemaErrors as err:
        logger.error("Schema validation failed for league game log")
        logger.error(f"Schema errors: {err.failure_cases}")
        logger.error(f"Invalid dataframe: {err.data}")
        dfs = None
    if save_to_db:
        dfs.to_sql("play_by_play", conn, if_exists="append", index=False)
    return dfs


def get_draft_combine_stats_helper(season, proxies):
    while True:
        try:
            df = DraftCombineStats(
                season_all_time=season, proxy=np.random.choice(proxies), timeout=3
            ).get_data_frames()[0]
            df.columns = df.columns.to_series().apply(lambda x: x.lower())
            return df
        except RequestException:
            continue
        except ValueError:
            return None


@log(logger)
def get_draft_combine_stats(proxies, season=None, save_to_db=False, conn=None):
    if season is None:
        seasons = [str(season) for season in range(1946, datetime.today().year + 1)]
        with Pool(len(seasons)) as p:
            dfs = p.map(
                partial(get_draft_combine_stats_helper, proxies=proxies), seasons
            )
    else:
        seasons = pd.Series([str(season)])
        with Pool(len(seasons)) as p:
            dfs = p.map(
                partial(get_draft_combine_stats_helper, proxies=proxies), seasons
            )
    dfs = pd.concat(dfs).reset_index(drop=True)
    try:
        dfs = DraftCombineStatsSchema.validate(dfs, lazy=True)
    except SchemaErrors as err:
        logger.error("Schema validation failed for draft combine stats")
        logger.error(f"Schema errors: {err.failure_cases}")
        logger.error(f"Invalid dataframe: {err.data}")
        dfs = None
    if save_to_db:
        dfs.to_sql("draft_combine_stats", conn, if_exists="replace", index=False)
    return dfs


def get_draft_history_helper(season, proxies):
    while True:
        try:
            df = DraftHistory(
                season_year_nullable=season, proxy=np.random.choice(proxies), timeout=3
            ).get_data_frames()[0]
            df.columns = df.columns.to_series().apply(lambda x: x.lower())
            return df
        except RequestException:
            continue
        except ValueError:
            return None


@log(logger)
def get_draft_history(proxies, season=None, save_to_db=False, conn=None):
    if season is None:
        seasons = [str(season) for season in range(1946, datetime.today().year + 1)]
        with Pool(len(seasons)) as p:
            dfs = p.map(partial(get_draft_history_helper, proxies=proxies), seasons)
    else:
        seasons = pd.Series([str(season)])
        with Pool(len(seasons)) as p:
            dfs = p.map(partial(get_draft_history_helper, proxies=proxies), seasons)
    dfs = pd.concat(dfs).reset_index(drop=True)
    try:
        dfs = DraftHistorySchema.validate(dfs, lazy=True)
    except SchemaErrors as err:
        logger.error("Schema validation failed for draft history")
        logger.error(f"Schema errors: {err.failure_cases}")
        logger.error(f"Invalid dataframe: {err.data}")
        dfs = None
    if save_to_db:
        dfs.to_sql("draft_history", conn, if_exists="replace", index=False)
    return dfs


def get_team_info_common_helper(team, proxies):
    while True:
        try:
            dfs = TeamInfoCommon(
                team_id=team, proxy=np.random.choice(proxies), timeout=3
            ).get_data_frames()
            dfs = pd.merge(dfs[0], dfs[1], on=["TEAM_ID"])
            dfs.columns = dfs.columns.to_series().apply(lambda x: x.lower())
            return dfs
        except RequestException:
            continue
        except ValueError:
            return None


@log(logger)
def get_team_info_common(proxies, save_to_db=False, conn=None):
    dfs = pd.read_sql("SELECT id FROM team", conn)["id"].tolist()
    num_workers = len(dfs)
    with Pool(num_workers) as p:
        dfs = p.map(partial(get_team_info_common_helper, proxies=proxies), dfs)
    dfs = pd.concat(dfs).reset_index(drop=True)
    try:
        dfs = TeamInfoCommonSchema.validate(dfs, lazy=True)
    except SchemaErrors as err:
        logger.error("Schema validation failed for team info common")
        logger.error(f"Schema errors: {err.failure_cases}")
        logger.error(f"Invalid dataframe: {err.data}")
        dfs = None
    if save_to_db:
        dfs.to_sql("team_info_common", conn, if_exists="replace", index=False)
    return dfs
