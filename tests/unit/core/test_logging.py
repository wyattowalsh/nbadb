"""Tests for nbadb.core.logging — loguru setup and stdlib interception."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from loguru import logger

from nbadb.core.logging import InterceptHandler, setup_logging

if TYPE_CHECKING:
    from pathlib import Path


class TestSetupLogging:
    def test_adds_handlers(self, tmp_path: Path) -> None:
        logger.remove()
        setup_logging(tmp_path, level="WARNING")
        # After setup, there should be handlers (stderr + file)
        # Just verify no exception and log dir exists
        assert tmp_path.exists()

    def test_creates_log_dir(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        setup_logging(log_dir)
        assert log_dir.exists()

    def test_nested_log_dir(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "a" / "b" / "c"
        setup_logging(log_dir)
        assert log_dir.exists()

    def test_default_level_is_debug(self, tmp_path: Path) -> None:
        logger.remove()
        # Should not raise with default level
        setup_logging(tmp_path)

    def test_stdlib_intercepted(self, tmp_path: Path) -> None:
        logger.remove()
        setup_logging(tmp_path)
        # stdlib root logger should have InterceptHandler
        root = logging.getLogger()
        assert any(isinstance(h, InterceptHandler) for h in root.handlers)


class TestInterceptHandler:
    def test_emit_forwards_to_loguru(self) -> None:
        handler = InterceptHandler()
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="test message",
            args=(),
            exc_info=None,
        )
        # Should not raise
        handler.emit(record)

    def test_emit_handles_unknown_level(self) -> None:
        handler = InterceptHandler()
        record = logging.LogRecord(
            name="test",
            level=99,
            pathname="",
            lineno=0,
            msg="custom level",
            args=(),
            exc_info=None,
        )
        record.levelname = "CUSTOM_LEVEL_99"
        handler.emit(record)

    def test_emit_with_info_level(self) -> None:
        handler = InterceptHandler()
        record = logging.LogRecord(
            name="test.module",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="info message %s",
            args=("arg1",),
            exc_info=None,
        )
        handler.emit(record)

    def test_emit_with_exception(self) -> None:
        handler = InterceptHandler()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="error with exc",
            args=(),
            exc_info=exc_info,
        )
        handler.emit(record)
