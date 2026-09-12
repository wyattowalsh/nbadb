from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from nbadb.orchestrate.successor_inode import (
    directory_inode,
    remove_empty_owned_directory,
)


def test_remove_empty_owned_directory_unlinks_only_the_moved_inode(tmp_path: Path) -> None:
    parent = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.mkdir("owned", 0o700, dir_fd=parent)
        held = os.open("owned", os.O_RDONLY | os.O_DIRECTORY, dir_fd=parent)
        try:
            expected = directory_inode(os.fstat(held))
            remove_empty_owned_directory(
                parent,
                "owned",
                held,
                expected_inode=expected,
                error=RuntimeError,
                label="owned scratch",
            )
            with pytest.raises(FileNotFoundError):
                os.stat("owned", dir_fd=parent, follow_symlinks=False)
            assert directory_inode(os.fstat(held)) == expected
        finally:
            os.close(held)
    finally:
        os.close(parent)
    assert list(tmp_path.iterdir()) == []


def test_remove_empty_owned_directory_restores_a_substituted_name(tmp_path: Path) -> None:
    parent = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.mkdir("owned", 0o700, dir_fd=parent)
        held = os.open("owned", os.O_RDONLY | os.O_DIRECTORY, dir_fd=parent)
        try:
            expected = directory_inode(os.fstat(held))
            os.rename("owned", "leaked", src_dir_fd=parent, dst_dir_fd=parent)
            os.mkdir("owned", 0o700, dir_fd=parent)
            with pytest.raises(RuntimeError, match="replaced at quarantine"):
                remove_empty_owned_directory(
                    parent,
                    "owned",
                    held,
                    expected_inode=expected,
                    error=RuntimeError,
                    label="owned scratch",
                )
            replacement = os.stat("owned", dir_fd=parent, follow_symlinks=False)
            leaked = os.stat("leaked", dir_fd=parent, follow_symlinks=False)
            assert directory_inode(replacement) != expected
            assert directory_inode(leaked) == expected
        finally:
            os.close(held)
        os.rmdir("owned", dir_fd=parent)
        os.rmdir("leaked", dir_fd=parent)
    finally:
        os.close(parent)
