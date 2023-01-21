"""**nba_db utilities**
"""
# -- Imports --------------------------------------------------------------------------
import os
import sqlite3
import subprocess

import pandas as pd
import requests
import swifter


# -- Functions -----------------------------------------------------------------------
def get_proxies() -> list[str]:
    """retrieves list of proxy addresses using the proxyscrape library

    Returns:
        list[str]: list of proxies of the form port:host
    """
    def check_proxy(proxy):
        try:
            res = requests.get(
                "http://example.com",
                proxies={'http': proxy},
                timeout=3
            )
            if res.ok:
                return proxy
        except IOError:
            return None
        else:
            return proxy
    proxies = pd.read_csv("https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt", header=None)
    df = pd.read_csv("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies_geolocation/http.txt", sep="|", header=None).iloc[:, 0]
    proxies = pd.concat([proxies, df]).drop_duplicates()
    df = pd.read_csv("https://raw.githubusercontent.com/saschazesiger/Free-Proxies/master/proxies/working.csv", header=None)
    df = pd.read_csv("https://raw.githubusercontent.com/saschazesiger/Free-Proxies/master/proxies/working.csv", header=None)
    df = df[df[1] == "http"].iloc[:, 0]
    proxies = pd.concat([proxies, df]).drop_duplicates()
    proxies = df.swifter.allow_dask_on_strings(enable=True).apply(check_proxy).dropna().tolist()
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