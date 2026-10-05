"""Regression: the 2026-09-25 12:49 PKT incident.

Friday's between-legs gap (12:00-14:32) passed the old current_leg()
guard, and the MARKET CLOSED card fired mid-session, lying "both bots
sleeping until Monday" while leg 2 was 1h43m away. The gate is now
sessions.session_over_for(): the WHOLE session must be done.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from psx_core import sessions  # noqa: E402

UTC = timezone.utc


class TestSessionOverFor:
    def test_friday_between_legs_gap_is_NOT_over(self):
        # The incident moment: Fri 12:49 PKT - leg 1 done, leg 2 at 14:32.
        moment = datetime(2026, 9, 25, 7, 49, tzinfo=UTC)
        assert sessions.session_over_for(moment) is False

    def test_friday_during_leg1_is_NOT_over(self):
        moment = datetime(2026, 9, 25, 4, 40, tzinfo=UTC)  # 09:40 PKT
        assert sessions.session_over_for(moment) is False

    def test_friday_after_leg2_IS_over(self):
        moment = datetime(2026, 9, 25, 11, 31, tzinfo=UTC)  # 16:31 PKT
        assert sessions.session_over_for(moment) is True

    def test_mon_thu_during_session_is_NOT_over(self):
        moment = datetime(2026, 9, 28, 5, 0, tzinfo=UTC)  # Mon 10:00 PKT
        assert sessions.session_over_for(moment) is False

    def test_mon_thu_after_close_IS_over(self):
        moment = datetime(2026, 9, 28, 11, 31, tzinfo=UTC)  # 16:31 PKT
        assert sessions.session_over_for(moment) is True

    def test_weekend_is_never_over(self):
        # Non-trading days: not a session at all -> not "session over".
        moment = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)  # Saturday
        assert sessions.session_over_for(moment) is False

    def test_close_card_blocked_in_the_gap(self, tmp_path, monkeypatch):
        """announce_close must refuse during the between-legs gap."""
        import session_cards as sc

        monkeypatch.setattr(sc, "CARDS_PATH", tmp_path / "cards.json")
        moment = datetime(2026, 9, 25, 7, 49, tzinfo=UTC)  # the incident
        ok, note = sc.announce_close(moment)
        assert ok is False
        assert "not fully over" in note
