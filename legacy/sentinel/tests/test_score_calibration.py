"""
Tests for the score-calibration fitter (src/score_calibration.py).

The contract is the honesty rule:
  * a thin ledger is REFUSED - status "insufficient", nothing written;
  * only trades with a stamped entry_score AND a closed net pnl count;
  * at floor: per-band win rates, band reliability flags, file written;
  * the 0.50 boundary aligns with the live conviction gate, the 0.70
    band edge with the Rule 22 ceiling (policy-relevant slices);
  * load() returns None when nothing was ever published.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import score_calibration as cal  # noqa: E402


def _trade(score, net, status="CLOSED"):
    return {
        "symbol": "TEST",
        "entry_score": score,
        "pnl_net_pct": net,
        "status": status,
    }


def _thick(n_per_band=21, win_rate=0.6):
    """Three healthy bands (>= floor both globally and per band)."""
    rows = []
    for lo in (0.50, 0.60, 0.70):
        for i in range(n_per_band):
            score = lo + 0.01 * (i % 10) + 0.001
            net = 1.9 if i < int(n_per_band * win_rate) else -1.0
            rows.append(_trade(round(score, 3), net))
    return rows


@pytest.fixture()
def tmp_out(tmp_path):
    return tmp_path / "calibration.json"


def test_thin_ledger_refused(tmp_out):
    verdict = cal.fit(trades=[_trade(0.55, 1.9)], out_path=tmp_out)
    assert verdict["status"] == "insufficient"
    assert "lying with math" in verdict["note"]
    assert not tmp_out.exists()  # nothing published


def test_only_stamped_closed_trades_count(tmp_out):
    rows = _thick()
    rows.append(_trade(None, 1.9))            # unstamped entry
    rows.append(_trade(0.55, 1.9, "OPEN"))    # not closed
    rows.append(_trade(0.55, None))           # no net pnl
    verdict = cal.fit(trades=rows, out_path=tmp_out)
    assert verdict["trades"] == len(rows) - 3


def test_bands_and_reliability(tmp_out):
    # 20 per band with a 0.6 win split = exactly 12/20 wins per band.
    rows = _thick(n_per_band=20, win_rate=0.6)
    verdict = cal.fit(trades=rows, out_path=tmp_out)
    assert verdict["status"] == "ok"
    assert [b["band"] for b in verdict["bands"]] == [
        "0.50-0.60",
        "0.60-0.70",
        "0.70-1.00",
    ]
    for b in verdict["bands"]:
        assert b["trades"] == 20
        assert b["reliable"] is True
        assert b["win_rate"] == pytest.approx(0.6, abs=0.02)
    published = json.loads(tmp_out.read_text(encoding="utf-8"))
    assert published["status"] == "ok"


def test_thin_band_flagged_unreliable_but_reported(tmp_out):
    # Global floor met; one band below the per-band floor.
    rows = _thick(n_per_band=20)
    rows += [_trade(0.501, 1.9), _trade(0.502, -1.0), _trade(0.503, 1.9)]
    verdict = cal.fit(trades=rows, out_path=tmp_out)
    assert verdict["status"] == "ok"
    first = verdict["bands"][0]
    assert first["trades"] == 20 + 3
    assert first["reliable"] is True
    # Simulate the thin case by raising the per-band floor.
    verdict2 = cal.fit(trades=rows, out_path=tmp_out, min_per_bucket=40)
    assert any(not b["reliable"] for b in verdict2["bands"])
    assert "unreliable" in verdict2["note"]


def test_band_edges_align_to_live_gates(tmp_out):
    # A score of exactly 0.50 belongs to the first band; 0.6999 to the
    # second; 0.70 exactly opens the ceiling band.
    rows = [
        _trade(0.50, 1.9),
        _trade(0.60, -1.0),
        _trade(0.70, 1.9),
    ] * 21
    verdict = cal.fit(trades=rows, out_path=tmp_out)
    t0, t1, t2 = (b["trades"] for b in verdict["bands"])
    assert (t0, t1, t2) == (21, 21, 21)


def test_load_returns_none_when_nothing_published(tmp_path):
    assert cal.load(cal_path=tmp_path / "missing.json") is None
