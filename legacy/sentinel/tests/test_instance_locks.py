"""Tests for the single-instance locks (2026-09-14 incident).

Two full bot stacks ran at once - a duplicate console spawned a second
bot on top of the running one - and the owner's CPU paid for both. The
locks make that class of accident impossible:

  * live._acquire_instance_lock: second claim while held -> False;
  * web_console._acquire_console_lock: same;
  * the lock releases on close, so a clean restart still works.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import live  # noqa: E402

pytest.importorskip(
    "flask", reason="web console tests need flask (not installed locally)"
)
import web_console  # noqa: E402


@pytest.fixture()
def lock_path(tmp_path):
    return tmp_path / "unit.lock"


def test_bot_lock_second_claim_refused(lock_path):
    assert live._acquire_instance_lock(lock_path) is True
    try:
        assert live._acquire_instance_lock(lock_path) is False
    finally:
        live._release_instance_lock()


def test_bot_lock_releases_for_restart(lock_path):
    assert live._acquire_instance_lock(lock_path) is True
    live._release_instance_lock()
    # A clean restart must succeed - the lock may never outlive its owner.
    assert live._acquire_instance_lock(lock_path) is True
    live._release_instance_lock()


def test_console_lock_second_claim_refused(lock_path):
    assert web_console._acquire_console_lock() is True
    try:
        assert web_console._acquire_console_lock() is False
    finally:
        handle = web_console._CONSOLE_LOCK_HANDLE
        if handle is not None:
            handle.close()
        web_console._CONSOLE_LOCK_HANDLE = None


def test_bot_lock_survives_child_read_of_same_file(lock_path):
    """The refused second claimant must not leave the file unlocked."""
    assert live._acquire_instance_lock(lock_path) is True
    try:
        for _ in range(3):
            assert live._acquire_instance_lock(lock_path) is False
    finally:
        live._release_instance_lock()
