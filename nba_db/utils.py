"""**nba_db utilities**
"""
# -- Imports --------------------------------------------------------------------------
import inspect
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import time
import traceback
from functools import wraps
from logging.config import fileConfig
from multiprocessing import Pool
from typing import Any, Callable, Dict, Sequence, Type

import pandas as pd
import requests

from nba_db.logger import log

logger = logging.getLogger("nba_db_logger")


# -- Functions -----------------------------------------------------------------------
def check_proxy(proxy):
    try:
        res = requests.get("http://example.com", proxies={"http": proxy}, timeout=3)
        if res.ok:
            return proxy
    except IOError:
        return None
    else:
        return None


@log(logger)
def get_proxies():
    """retrieves list of proxy addresses using the proxyscrape library

    Returns:
        list[str]: list of proxies of the form port:host
    """
    logger.info("Retrieving proxies...")
    proxies = pd.read_csv(
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        header=None,
    )
    df = (
        pd.read_csv(
            "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
            sep="|",
            header=None,
        )
        .iloc[:, 0]
        .reset_index(drop=True)
    )
    proxies = (
        pd.concat([proxies, df])
        .drop_duplicates()
        .reset_index(drop=True)
        .values.tolist()
    )
    proxies = [p for sublist in proxies for p in sublist]
    logger.info(f"Found {len(proxies)} proxies. Checking proxies...")
    with Pool(250) as p:
        proxies = p.map(check_proxy, proxies)
    proxies = pd.Series(proxies).dropna().tolist()
    logger.info(f"Found {len(proxies)} valid proxies. Returning proxies...")
    return proxies


@log(logger)
def get_db_conn():
    logger.info("Connecting to database...")
    db_name = "nba-db/nba.sqlite"
    conn = sqlite3.connect(db_name)
    logger.info("Connected to database. Returning connection object...")
    return conn


@log(logger)
def download_db():
    logger.info("Downloading database...")
    subprocess.run(
        "kaggle datasets download --unzip -o -q -d wyattowalsh/basketball", shell=True
    )
    try:
        os.mkdir("nba-db")
    except FileExistsError:
        logger.warning("nba-db directory already exists. Removing...")
        shutil.rmtree("nba-db")
        os.mkdir("nba-db")
    shutil.move("nba.sqlite", "nba-db/nba.sqlite")
    shutil.move("csv", "nba-db/csv")
    subprocess.run(
        "wget https://raw.githubusercontent.com/wyattowalsh/nba-db/main/dataset-metadata.json -P nba-db",
        shell=True,
    )


@log(logger)
def upload_new_db_version(message):
    logger.info("Uploading new database version...")
    files_to_rm = [".DS_Store", ".ipynb_checkpoints"]
    os.chdir("nba-db")
    for file in files_to_rm:
        subprocess.run(f"find . -name '{file}' -delete", shell=True)
    os.chdir("..")
    subprocess.run(
        f"kaggle datasets version -m '{message}' -p nba-db --dir-mode zip", shell=True
    )
    logger.info("Uploaded new database version.")


@log(logger)
def dump_db(conn):
    tables = pd.read_sql(
        "SELECT name FROM sqlite_schema WHERE type ='table' AND name NOT LIKE 'sqlite_%';",
        conn,
    )["name"]
    logger.info(f"Dumping {len(tables)} database tables to csv files...")
    # check if csv directory exists
    try:
        os.mkdir("nba-db/csv")
    except FileExistsError:
        logger.warning("csv directory already exists. Removing...")
        shutil.rmtree("nba-db/csv")
        os.mkdir("nba-db/csv")
    for table in tables:
        data = pd.read_sql(f"SELECT * FROM {table}", conn)
        data.to_csv(f"nba-db/csv/{table}.csv", index=False)
    logger.info("Dumped database tables to csv files.")
