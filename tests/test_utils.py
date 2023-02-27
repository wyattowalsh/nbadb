"""test_utils.py -- Tests for the utils module.
"""
# -- Imports --------------------------------------------------------------------------
import os
from sqlite3 import Connection

from hypothesis import example, given
from hypothesis import strategies as st
from hypothesis.extra.pandas import column, data_frames
from nba_db.utils import download_db, dump_db, get_db_conn, get_proxies


# -- Tests ---------------------------------------------------------------------------
def test_get_proxies():
    proxies = get_proxies()
    assert isinstance(proxies, list)
    assert len(proxies) > 0
    assert all(isinstance(proxy, str) for proxy in proxies)
    assert all(len(proxy.split(":")) == 2 for proxy in proxies)
    assert all(all(char.isdigit() for char in proxy.split(":")[0]) for proxy in proxies)
    assert all(all(char.isdigit() for char in proxy.split(":")[1]) for proxy in proxies)


def test_get_db_conn():
    conn = get_db_conn()
    assert isinstance(conn, Connection)


def test_download_db():
    download_db()
    assert os.path.isdir("basketball")
    assert os.path.isfile("basketball/basketball.sqlite")


def test_dumb_db():
    conn = get_db_conn()
    dump_db(conn)
    tables = pd.read_sql("SELECT name FROM sqlite_schema WHERE type ='table' AND name NOT LIKE 'sqlite_%';", conn)['name']
    num_tables = len(tables)
    assert os.path.isdir("basketball")
    assert os.path.isfile("basketball/basketball.sqlite")
    assert os.path.isdir("basketball/csv")
    assert len(os.listdir("basketball/csv")) == num_tables
    for table in tables:
        assert os.path.isfile(f"basketball/csv/{table}.csv")