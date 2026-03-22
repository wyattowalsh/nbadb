"""Shared Python sandbox preamble for MCP sandbox and Copilot backend."""

from __future__ import annotations

_PREAMBLE_TEMPLATE = '''\
import sys
import json
import warnings
warnings.filterwarnings("ignore")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Monkey-patch plt.show() to capture figures as base64 PNG
import io as _io
import base64 as _b64

_original_show = plt.show

def _patched_show(*args, **kwargs):
    buf = _io.BytesIO()
    plt.savefig(buf, format="png", dpi=120, bbox_inches="tight",
                facecolor="#141a2e", edgecolor="none")
    buf.seek(0)
    img_b64 = _b64.b64encode(buf.read()).decode()
    print(json.dumps({{"image_base64": img_b64, "format": "png"}}))
    plt.close("all")

plt.show = _patched_show

import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import duckdb

try:
    import scipy.stats as stats
except ImportError:
    pass

# Read-only database connection
conn = duckdb.connect("{db_path}", read_only=True)

# NBA metric calculator and skill scripts
sys.path.insert(0, "{skills_dir}")
try:
    import metric_calculator as mc
    import team_colors
    import season_utils
except ImportError:
    pass

def query(sql: str) -> pd.DataFrame:
    """Shorthand to run SQL and return a DataFrame."""
    return conn.execute(sql).fetchdf()

def chart(fig):
    """Output a Plotly figure for display in the chat."""
    print(fig.to_json())

def table(df):
    """Output a DataFrame for display in the chat."""
    print(df.to_json(orient="split"))

def show(data):
    """Smart output — auto-detects Plotly figures vs DataFrames."""
    if hasattr(data, "to_json") and hasattr(data, "data") and hasattr(data, "layout"):
        chart(data)
    elif isinstance(data, pd.DataFrame):
        table(data)
    else:
        print(data)
'''


def build_preamble(db_path: str, skills_dir: str) -> str:
    """Build the Python sandbox preamble with the given DB path and skills dir."""
    return _PREAMBLE_TEMPLATE.format(db_path=db_path, skills_dir=skills_dir)
