"""Regression: 2026-10-02 red audit on a healthy corporate-actions map.

check_corporate() used result.get("bySymbol", {}) on the dict that
load_map() returns - but load_map() ALREADY unwraps the stored file's
bySymbol. The double unwrap always produced {} -> "0 book-closure
carriers on 0 symbols" -> a false RED on the owner's phone.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import self_audit  # noqa: E402


def test_check_corporate_reads_stored_map(tmp_path, monkeypatch):
    by_symbol = {
        "PPL": {"notices": ["AGM"], "results": []},
    }
    # the RED threshold is <10 book-closure carriers - give the GREEN
    # case exactly 10 so the test also pins the threshold boundary
    for i in range(10):
        by_symbol[f"SYM{i:02d}"] = {
            "notices": ["Final cash dividend"],
            "results": [],
            "book_closure_from": "2026-10-10",
            "book_closure_to": "2026-10-10",
        }
    stored = {
        "fetchedAt": "2026-09-24T10:23:09.779769+00:00",
        "records": 190,
        "bySymbol": by_symbol,
    }
    fake = tmp_path / "corporate_actions.json"
    fake.write_text(json.dumps(stored), encoding="utf-8")
    monkeypatch.setattr(
        "corporate_actions.OUTPUT", fake, raising=False
    )

    verdict, detail = self_audit.check_corporate()

    assert verdict == "GREEN", detail
    assert "10 book-closure carriers" in detail
    assert "11 symbols" in detail


def test_check_corporate_still_red_when_map_empty(tmp_path, monkeypatch):
    fake = tmp_path / "corporate_actions.json"
    fake.write_text(json.dumps({"bySymbol": {}}), encoding="utf-8")
    monkeypatch.setattr("corporate_actions.OUTPUT", fake, raising=False)

    verdict, detail = self_audit.check_corporate()

    assert verdict == "RED"
    assert "0 book-closure carriers" in detail
