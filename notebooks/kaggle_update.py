"""Kaggle cron notebook for nbadb automated updates.

Schedule: Daily at 06:00 UTC (after NBA games complete).
Monthly full refresh on days 1-7.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

# Install nbadb in Kaggle environment
subprocess.check_call(
    [sys.executable, "-m", "pip", "install", "-e", "."],
    stdout=subprocess.DEVNULL,
)

from nbadb.core.config import NbaDbSettings
from nbadb.kaggle.client import KaggleClient
from nbadb.kaggle.notebook import determine_update_mode, print_summary
from nbadb.orchestrate import Orchestrator

mode = determine_update_mode()
settings = NbaDbSettings(data_dir=Path("/kaggle/working/nbadb"))
orchestrator = Orchestrator(settings)

if mode == "monthly":
    result = asyncio.run(orchestrator.run_monthly())
else:
    result = asyncio.run(orchestrator.run_daily())

print_summary(
    mode, result.tables_updated, result.rows_total, result.duration_seconds
)

# Upload to Kaggle
client = KaggleClient()
client.ensure_metadata(settings.data_dir)
client.upload(settings.data_dir, version_notes=f"{mode} update")
