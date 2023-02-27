"""**nba_db utilities**
"""
# -- Imports --------------------------------------------------------------------------
import logging
import os
import sqlite3
import subprocess
from logging.config import fileConfig
from multiprocessing import Pool

import pandas as pd
import requests

# -- Logging --------------------------------------------------------------------------
fileConfig("./utils/logging.conf")
logger = logging.getLogger("backetball_db_logger")


# -- Functions -----------------------------------------------------------------------
def check_proxy(proxy):
    try:
        res = requests.get(
            "http://example.com",
            proxies={
                'http': proxy
            },
            timeout=3
        )
        if res.ok:
            return proxy
    except IOError:
        return None
    else:
        return None


def get_proxies():
    """retrieves list of proxy addresses using the proxyscrape library

    Returns:
        list[str]: list of proxies of the form port:host
    """
    proxies = pd.read_csv("https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt", header=None)
    df = pd.read_csv("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies_geolocation/http.txt", sep="|", header=None).iloc[:, 0].reset_index(drop=True)
    proxies = pd.concat([proxies, df]).drop_duplicates().reset_index(drop=True).values.tolist()
    proxies = [p for sublist in proxies for p in sublist]
    with Pool(250) as p:
        proxies = p.map(check_proxy, proxies)
    proxies = pd.Series(proxies).dropna().tolist()
    return proxies


def combine_team_games(df):
    '''source: https://github.com/swar/nba_api/blob/master/docs/examples/Finding%20Games.ipynb
        modified source

        Combine a TEAM_ID-GAME_ID unique table into rows by game. Slow.

        Parameters
        ----------
        df : Input DataFrame.
        
        Returns
        -------
        result : DataFrame
    '''
    # Join every row to all others with the same game ID.
    joined = pd.merge(df, df, suffixes=['_HOME', '_AWAY'],
                      on=['SEASON_ID', 'GAME_ID', 'GAME_DATE'])
    # Filter out any row that is joined to itself.
    result = joined[joined.TEAM_ID_HOME != joined.TEAM_ID_AWAY]
    result = result[result.MATCHUP_HOME.str.contains(' vs. ')].reset_index(drop=True)
    return result


def get_db_conn():
    db_name = "basketball/basketball.sqlite"
    con = sqlite3.connect(db_name)
    return con


def download_db():
    subprocess.run("kaggle datasets download --unzip -o -q -d wyattowalsh/basketball", shell=True)


def upload_new_db_version(message):
    files_to_rm = [".DS_Store", ".ipynb_checkpoints"]
    os.chdir("basketball")
    for file in files_to_rm:
        subprocess.run(f"find . -name '{file}' -delete", shell=True)
    os.chdir("..")
    subprocess.run(f"kaggle datasets version -m '{message}' -p basketball --dir-mode zip", shell=True)


def dump_db(conn):
    tables = pd.read_sql("SELECT name FROM sqlite_schema WHERE type ='table' AND name NOT LIKE 'sqlite_%';", conn)['name']
    for table in tables:
        data = pd.read_sql(f"SELECT * FROM {table}", conn)
        data.to_csv(f"basketball/csv/{table}.csv", index=False)