"""**nba_db utilities**
"""
# -- Imports --------------------------------------------------------------------------
import sqlite3
import subprocess

import pandas as pd
import requests
import swifter
from nba_api.stats.static import players, teams


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
    # url = "https://raw.githubusercontent.com/saschazesiger/Free-Proxies/master/proxies/working.csv"
    df = pd.read_csv("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies_geolocation/http.txt", sep="|", header=None)
    df = df.iloc[:, 0] #df[df[1] == "United States"].iloc[:, 0]
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
    db_name = "basketball/basketball.db"
    con = sqlite3.connect(db_name)
    return con


def download_db():
    subprocess.run("kaggle datasets download -d wyattowalsh/basketball", shell=True)
    subprocess.run("unzip basketball.zip", shell=True)
    subprocess.run("rm basketball.zip", shell=True)

def upload_new_db_version():
    pass