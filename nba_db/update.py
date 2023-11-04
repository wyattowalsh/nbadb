"""database update functions
"""
# -- Imports --------------------------------------------------------------------------
import logging
import os
import shutil
import subprocess
from datetime import datetime

import pandas as pd

from nba_db.extract import (
    get_box_score_summaries,
    get_draft_combine_stats,
    get_draft_history,
    get_league_game_log_all,
    get_league_game_log_from_date,
    get_play_by_play,
    get_player_info,
    get_players,
    get_team_info_common,
    get_teams,
    get_teams_details,
)
from nba_db.logger import log
from nba_db.utils import (
    download_db,
    dump_db,
    get_db_conn,
    get_proxies,
    upload_new_db_version,
)

logger = logging.getLogger("nba_db_logger")


# -- Functions -----------------------------------------------------------------------
@log(logger)
def init():
    try:
        os.mkdir("nba-db")
    except FileExistsError:
        logger.warning("nba directory already exists. Removing...")
        shutil.rmtree("nba-db")
        os.mkdir("nba-db")
    subprocess.run(
        "wget https://raw.githubusercontent.com/wyattowalsh/nba-db/main/dataset-metadata.json -P nba-db",
        shell=True,
    )
    proxies = get_proxies()
    conn = get_db_conn()
    get_players(True, conn)
    get_teams(True, conn)
    get_league_game_log_all(proxies, conn)
    get_teams_details(proxies, True, conn)
    get_player_info(proxies, True, conn)
    game_ids = pd.read_sql("SELECT game_id FROM game", conn).game_id.to_list()
    get_box_score_summaries(game_ids, proxies, True, conn)
    get_play_by_play(game_ids, proxies, True, conn)
    get_draft_combine_stats(proxies, None, True, conn)
    get_draft_history(proxies, None, True, conn)
    get_team_info_common(proxies, True, conn)
    dump_db(conn)
    # upload new db version to Kaggle
    version_message = f"Daily update: {pd.to_datetime('today').strftime('%Y-%m-%d')}"
    upload_new_db_version(version_message)
    # close db connection
    conn.close()


@log(logger)
def daily():
    # download db from Kaggle
    download_db()
    # get proxies and establish db connenction
    proxies = get_proxies()
    conn = get_db_conn()
    # get latest date in db and add a day
    latest_db_date = pd.read_sql("SELECT MAX(GAME_DATE) FROM game", conn).iloc[0, 0]
    # check if today is a game day
    if pd.to_datetime(latest_db_date) >= pd.to_datetime(datetime.today().date()):
        logger.info("No new games today. Exiting...")
        return
    # add a day to latest db date
    latest_db_date = (pd.to_datetime(latest_db_date) + pd.Timedelta(days=1)).strftime(
        "%Y-%m-%d"
    )
    # get new games and add to db
    df = get_league_game_log_from_date(
        latest_db_date, proxies, save_to_db=True, conn=conn
    )
    if len(df) == 0:
        conn.close()
        return 0
    games = df["game_id"].unique().tolist()
    # get box score summaries and play by play for new games
    get_box_score_summaries(games, proxies, save_to_db=True, conn=conn)
    get_play_by_play(games, proxies, save_to_db=True, conn=conn)
    # dump db tables to csv
    dump_db(conn)
    # upload new db version to Kaggle
    version_message = f"Daily update: {pd.to_datetime('today').strftime('%Y-%m-%d')}"
    upload_new_db_version(version_message)
    # close db connection
    conn.close()


@log(logger)
def monthly():
    # download db from Kaggle
    download_db()
    # get proxies and establish db connenction
    proxies = get_proxies()
    conn = get_db_conn()
    # update players & teams
    get_players(save_to_db=True, conn=conn)
    get_teams(save_to_db=True, conn=conn)
    get_player_info(proxies=proxies, save_to_db=True, conn=conn)
    get_teams_details(proxies=proxies, save_to_db=True, conn=conn)
    get_draft_combine_stats(proxies=proxies, season=None, save_to_db=True, conn=conn)
    get_draft_history(proxies=proxies, season=None, save_to_db=True, conn=conn)
    get_team_info_common(proxies=proxies, save_to_db=True, conn=conn)
    # upload new db version to Kaggle
    version_message = f"Monthly update: {pd.to_datetime('today').strftime('%Y-%m-%d')}"
    upload_new_db_version(version_message)
    # close db connection
    conn.close()
