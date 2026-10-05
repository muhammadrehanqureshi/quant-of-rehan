"""
Tests for Rule 12c - the institutional pump/dump leaders (v0.16.2).

Pins the 2026-09-16 request: "which institutions are pumping and
dumping WHAT" - surfaced from the NCCPL investor-type history the bot
has stored since v0.10.0, but previously only Foreign/retail were
read. Advisory only: the reads ride in decision metadata and
SIGNALS.md and can never veto a decision by themselves.
"""

from __future__ import annotations

import market_regime
import notify


def _row(date: str, by_inv: dict[str, dict]) -> dict:
    return {"date": date, "net_total_usd": None, "byInvestor": by_inv}


SEP15 = {
    "Mutual Funds": {"buy": 16e6, "sell": 22.5e6, "net": -6.5e6},
    "Banks / DFI": {"buy": 15.7e6, "sell": 10.2e6, "net": +5.6e6},
    "Foreign": {"buy": 6.2e6, "sell": 5.7e6, "net": +0.5e6},
    "Individuals": {"buy": 60.9e6, "sell": 60.0e6, "net": +0.9e6},
    "Brokers": {"buy": 10.4e6, "sell": 10.9e6, "net": -0.6e6},
}


def test_top_buyer_and_seller_named():
    out = market_regime.institutional_state([_row("2026-09-15", SEP15)])
    assert out["top_buyer"] == {"name": "Banks / DFI", "net_usd": 5.6e6}
    assert out["top_seller"] == {"name": "Mutual Funds", "net_usd": -6.5e6}


def test_absent_when_no_investor_rows():
    out = market_regime.institutional_state(
        [{"date": "2026-09-15", "net_total_usd": -1e6}]
    )
    assert "top_buyer" not in out
    assert "top_seller" not in out


def test_single_investor_row_still_names_both():
    out = market_regime.institutional_state(
        [_row("2026-09-15", {"Foreign": {"net": +2e6}})]
    )
    # One row is both the best buyer and the worst seller - degenerate
    # but honest; both fields exist and name the same investor.
    assert out["top_buyer"]["name"] == "Foreign"
    assert out["top_seller"]["name"] == "Foreign"


def test_context_fields_exist():
    ctx = market_regime.MarketContext()
    assert ctx.inst_top_buyer is None
    assert ctx.inst_top_seller is None


def test_signals_md_flow_headline(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    latest = _row("2026-09-15", SEP15)
    # The WHAT: per-investor sector breakdown for the leaders.
    latest["matrix"] = {
        "Banks / DFI": {"Commercial Banks": 2.9e6, "Cement": -3.8e6},
        "Mutual Funds": {"Cement": -9.8e6, "Commercial Banks": -0.5e6},
    }
    (data / "foreign_flow_history.jsonl").write_text(
        "\n".join(
            [json.dumps(_row("2026-09-14", SEP15)), json.dumps(latest)]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(notify, "ROOT", tmp_path)
    line = notify._flow_headline()
    assert line is not None
    assert "Banks / DFI +5.6M in Commercial Banks" in line
    assert "Mutual Funds -6.5M in Cement" in line
    assert "2026-09-15" in line  # the LATEST row, not an earlier one


def test_signals_md_headline_survives_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(notify, "ROOT", tmp_path)
    assert notify._flow_headline() is None


def test_signals_md_headline_survives_corrupt_file(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    (data / "foreign_flow_history.jsonl").write_text(
        "{corrupt\n", encoding="utf-8"
    )
    monkeypatch.setattr(notify, "ROOT", tmp_path)
    assert notify._flow_headline() is None


import json  # noqa: E402  (used by the fixture helper above)
