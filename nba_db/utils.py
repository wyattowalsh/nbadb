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
logger = logging.getLogger("nba_db_logger")


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
    logger.info("Retrieving proxies...")
    proxies = pd.read_csv("https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt", header=None)
    df = pd.read_csv("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies_geolocation/http.txt", sep="|", header=None).iloc[:, 0].reset_index(drop=True)
    proxies = pd.concat([proxies, df]).drop_duplicates().reset_index(drop=True).values.tolist()
    proxies = [p for sublist in proxies for p in sublist]
    logger.info(f"Found {len(proxies)} proxies. Checking proxies...")
    with Pool(250) as p:
        proxies = p.map(check_proxy, proxies)
    proxies = pd.Series(proxies).dropna().tolist()
    logger.info(f"Found {len(proxies)} valid proxies. Returning proxies...")
    return proxies


def get_db_conn():
    logger.info("Connecting to database...")
    db_name = "nba/nba.sqlite"
    conn = sqlite3.connect(db_name)
    logger.info("Connected to database. Returning connection object...")
    return conn


def download_db():
    logger.info("Downloading database...")
    subprocess.run("kaggle datasets download --unzip -o -q -d wyattowalsh/nba", shell=True)


def upload_new_db_version(message):
    logger.info("Uploading new database version...")
    files_to_rm = [".DS_Store", ".ipynb_checkpoints"]
    os.chdir("nba")
    for file in files_to_rm:
        subprocess.run(f"find . -name '{file}' -delete", shell=True)
    os.chdir("..")
    subprocess.run(f"kaggle datasets version -m '{message}' -p nba --dir-mode zip", shell=True)
    logger.info("Uploaded new database version.")


def dump_db(conn):
    tables = pd.read_sql("SELECT name FROM sqlite_schema WHERE type ='table' AND name NOT LIKE 'sqlite_%';", conn)['name']
    logger.info(f"Dumping {len(tables)} database tables to csv files...")
    for table in tables:
        data = pd.read_sql(f"SELECT * FROM {table}", conn)
        data.to_csv(f"nba/csv/{table}.csv", index=False)
    logger.info("Dumped database tables to csv files.")