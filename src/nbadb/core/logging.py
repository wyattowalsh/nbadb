from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from pathlib import Path


def setup_logging(log_dir: Path, level: str = "DEBUG") -> None:
    """Configure loguru with console + JSON file sinks."""
    logger.remove()  # Remove default handler

    # Console sink: colored, human-readable
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    # JSON file sink: structured, for machine parsing
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_dir / "nbadb_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        format="{message}",
        serialize=True,  # JSON output
        rotation="1 day",
        retention="30 days",
        compression="gz",
    )

    # Intercept stdlib logging -> loguru
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)


class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


__all__ = ["setup_logging", "logger"]
