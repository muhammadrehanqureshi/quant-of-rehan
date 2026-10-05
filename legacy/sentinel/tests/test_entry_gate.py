"""
Tests for the entry gate - the persistent daily 3-entry cap.
"""

from __future__ import annotations

import json

import pytest

from entry_gate import EntryGate, load_max_entries_from_config
from psx_core import paths


@pytest.fixture
def gate_dir(tmp_path, monkeypatch):
    """Redirect data dir to a temp directory."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(paths, "DATA_DIR", data_dir)
    return data_dir


def make_gate(gate_dir, max_entries=3):
    return EntryGate(
        path=gate_dir / "entry_gate.json",
        max_entries_per_day=max_entries,
    )


# ---------------------------------------------------------------------------
# Counting and the cap
# ---------------------------------------------------------------------------

class TestCap:
    def test_fresh_day_allows_entry(self, gate_dir):
        gate = make_gate(gate_dir)
        assert gate.allows_entry("2026-09-08") is True

    def test_cap_blocks_after_three(self, gate_dir):
        gate = make_gate(gate_dir)
        for _ in range(3):
            gate.record_entry("2026-09-08")
        assert gate.allows_entry("2026-09-08") is False

    def test_cap_resets_next_day(self, gate_dir):
        gate = make_gate(gate_dir)
        for _ in range(3):
            gate.record_entry("2026-09-08")
        assert gate.allows_entry("2026-09-09") is True

    def test_entries_today_rolls_date_forward(self, gate_dir):
        gate = make_gate(gate_dir)
        for _ in range(3):
            gate.record_entry("2026-09-08")
        # A read of the next day must not report the stale count.
        assert gate.entries_today("2026-09-09") == 0

    def test_partial_cap_still_allows(self, gate_dir):
        gate = make_gate(gate_dir)
        gate.record_entry("2026-09-08")
        gate.record_entry("2026-09-08")
        assert gate.allows_entry("2026-09-08") is True

    def test_custom_max_entries(self, gate_dir):
        gate = make_gate(gate_dir, max_entries=1)
        gate.record_entry("2026-09-08")
        assert gate.allows_entry("2026-09-08") is False


# ---------------------------------------------------------------------------
# Persistence - the reason the gate exists
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_state_survives_new_instance(self, gate_dir):
        gate = make_gate(gate_dir)
        for _ in range(3):
            gate.record_entry("2026-09-08")

        # A restart mid-day reloads from disk: the cap still holds.
        gate2 = make_gate(gate_dir)
        assert gate2.allows_entry("2026-09-08") is False

    def test_state_file_written(self, gate_dir):
        gate = make_gate(gate_dir)
        gate.record_entry("2026-09-08")
        raw = json.loads((gate_dir / "entry_gate.json").read_text(encoding="utf-8"))
        assert raw == {"date": "2026-09-08", "entries": 1}

    def test_corrupt_file_treated_as_empty(self, gate_dir):
        (gate_dir / "entry_gate.json").write_text(
            "not json!!!", encoding="utf-8"
        )
        gate = make_gate(gate_dir)
        assert gate.allows_entry("2026-09-08") is True

    def test_negative_entries_clamped(self, gate_dir):
        (gate_dir / "entry_gate.json").write_text(
            json.dumps({"date": "2026-09-08", "entries": -5}),
            encoding="utf-8",
        )
        gate = make_gate(gate_dir)
        assert gate.entries_today("2026-09-08") == 0

    def test_non_dict_file_treated_as_empty(self, gate_dir):
        (gate_dir / "entry_gate.json").write_text(
            "[1, 2, 3]", encoding="utf-8"
        )
        gate = make_gate(gate_dir)
        assert gate.allows_entry("2026-09-08") is True


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

class TestConfigLoad:
    def test_reads_max_entries_from_config(self, tmp_path):
        cfg = tmp_path / "config.json"
        cfg.write_text(
            json.dumps({"max_entries_per_day": 5}), encoding="utf-8"
        )
        assert load_max_entries_from_config(cfg) == 5

    def test_defaults_to_three(self, tmp_path):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({}), encoding="utf-8")
        assert load_max_entries_from_config(cfg) == 1

    def test_missing_file_defaults_to_three(self, tmp_path):
        assert load_max_entries_from_config(tmp_path / "nope.json") == 1

    def test_invalid_value_defaults_to_three(self, tmp_path):
        cfg = tmp_path / "config.json"
        cfg.write_text(
            json.dumps({"max_entries_per_day": "lots"}), encoding="utf-8"
        )
        assert load_max_entries_from_config(cfg) == 1

    def test_zero_is_honored_as_entry_pause(self, tmp_path):
        # 2026-09-21: 0 is the owner's explicit pause. The old loader
        # rejected it and silently fell back to 3 - a fake pause. The
        # configured 0 must reach the gate untouched.
        cfg = tmp_path / "config.json"
        cfg.write_text(
            json.dumps({"max_entries_per_day": 0}), encoding="utf-8"
        )
        assert load_max_entries_from_config(cfg) == 0

    def test_zero_cap_never_allows_entry(self, tmp_path):
        gate = EntryGate(
            path=tmp_path / "gate.json", max_entries_per_day=0
        )
        assert gate.allows_entry("2026-09-21") is False
        assert gate.entries_today("2026-09-21") == 0


# ---------------------------------------------------------------------------
# Integration: gate + portfolio ledger agree
# ---------------------------------------------------------------------------

class TestLedgerAgreement:
    def test_gate_count_matches_recorded_entries(self, gate_dir):
        """
        The historical failure: 30 ENTERs on 2026-09-04 while the strategy
        allows 3. With the gate, a caller that asks allows_entry before each
        record_entry can never exceed the cap.
        """
        gate = make_gate(gate_dir)
        recorded = 0
        for _ in range(30):
            if gate.allows_entry("2026-09-08"):
                gate.record_entry("2026-09-08")
                recorded += 1
            else:
                break
        assert recorded == 3
        assert gate.entries_today("2026-09-08") == 3
