"""
Tests for v0.16.5 - the honest-ledger changes.

Pins:
  * net-of-cost accounting on closed positions (the full PSX fee
    stack: both commission bands, SST, levies, 15% CGT);
  * the Rule 12c mutual-fund-dump conviction bump end-to-end:
    lessons computation -> read-time view -> engine conviction gate;
  * the cap that keeps stacked lessons from making the gate
    unreachable.
"""

from __future__ import annotations

import json

import pytest

import decision_engine
import exit_frontier
import lessons
import portfolio as portfolio_mod


# --------------------------- net ledger -----------------------------------


def test_net_pnl_exact_for_dear_stock_profit():
    # MARI-like: buy 659.92, sell 660.30 (+0.38 gross ≈ +0.06%).
    entry, exit_ = 659.92, 660.30
    net = exit_frontier.net_pnl_pct(entry, exit_)
    gross = (exit_ / entry - 1.0) * 100.0
    assert net < gross  # costs + tax bite
    # Round-trip at 0.15%/side + SST + levies ≈ 0.448% of value; here
    # it dominates the tiny gross gain, so net must be negative.
    assert net < 0


def test_net_pnl_loss_is_deeper_than_gross():
    # A -2% stop on a 100-PKR stock: costs ~0.448%, no tax on losses.
    net = exit_frontier.net_pnl_pct(100.0, 98.0)
    assert -2.6 < net < -2.2


def test_bare_portfolio_default_is_sandboxed_under_pytest(tmp_path, monkeypatch):
    """v2.1.1: Portfolio() with no path under pytest must NEVER resolve
    to the production book. This is the guard that makes the 2026-09-18
    TEST-rows-in-production leak structurally impossible."""
    import os

    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests::guard")
    book = portfolio_mod.Portfolio()
    assert book.portfolio_file.name == "portfolio.test-sandbox.json"
    assert book.portfolio_file != portfolio_mod.paths.DATA_DIR / "portfolio.json"


def test_bare_portfolio_outside_pytest_still_uses_production(tmp_path, monkeypatch):
    """The live bot and cloud passes must keep their real book: the
    sandbox applies ONLY under pytest."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    book = portfolio_mod.Portfolio()
    assert book.portfolio_file == portfolio_mod.paths.DATA_DIR / "portfolio.json"


def test_net_pnl_cheap_stock_fee_explosion():
    # KEL at 6.67: 0.03 PKR/share/side ≈ 0.45%/side -> ~0.9%+ round
    # trip. A flat gross day is a real net loss.
    net = exit_frontier.net_pnl_pct(6.67, 6.67)
    assert net < -0.8


def test_closed_position_records_net_pnl(tmp_path):
    # v2.1.1: the bare Portfolio() default is sandboxed under pytest
    # (it once appended TEST rows to the owner's LIVE book); the
    # explicit tmp_path form is used here anyway: tests own their
    # data, always.
    book = portfolio_mod.Portfolio(portfolio_file=tmp_path / "portfolio.json")
    pos = book.open_position(
        symbol="TEST",
        entry_price=100.0,
        entry_date="2026-09-16",
        target_price=102.0,
    )
    book._close_position(pos, 102.0, "2026-09-16", "profit")
    snap = pos.to_dict()
    assert snap["pnl_pct"] == pytest.approx(2.0, abs=0.01)
    assert snap["pnl_net_pct"] is not None
    # 2% gross on a 100-PKR stock nets below gross after costs+tax.
    assert snap["pnl_net_pct"] < snap["pnl_pct"]
    assert snap["pnl_net_pct"] > 0  # still a win net of everything


# ------------------- MF-dump conviction bump ------------------------------


@pytest.fixture()
def flow_env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(lessons.paths, "DATA_DIR", data)
    return data


def _write_flow(data_dir, mf_net):
    row = {
        "date": "2026-09-16",
        "net_total_usd": None,
        "byInvestor": {"Mutual Funds": {"buy": 1e6, "sell": 1e6, "net": mf_net}},
        "matrix": {},
    }
    (data_dir / "foreign_flow_history.jsonl").write_text(
        json.dumps(row) + "\n", encoding="utf-8"
    )


def test_mf_dump_day_raises_conviction_bar(flow_env):
    _write_flow(flow_env, -6.5e6)
    ls = lessons.compute_lessons("2026-09-16")
    assert ls["mf_dump"]["net_usd"] == -6.5e6
    assert ls["min_master_score_adjustment"] == 0.03


def test_mf_buy_day_leaves_bar_alone(flow_env):
    _write_flow(flow_env, +5.6e6)
    ls = lessons.compute_lessons("2026-09-16")
    assert "mf_dump" not in ls
    assert ls.get("min_master_score_adjustment") in (None, 0.0)


def test_read_time_view_carries_bump(flow_env):
    _write_flow(flow_env, -6.5e6)
    lessons.refresh_lessons("2026-09-16")
    view = lessons.load_lessons()
    assert view["min_master_score_adjustment"] == pytest.approx(0.03)


def test_engine_gate_uses_the_bump(flow_env):
    _write_flow(flow_env, -6.5e6)
    lessons.refresh_lessons("2026-09-16")
    engine = decision_engine.DecisionEngine(lessons=lessons.load_lessons())
    base = decision_engine.DecisionConfig().min_master_score
    assert engine.effective_min_master_score == pytest.approx(base + 0.03)


def test_stacked_lessons_capped_at_point_zero_eight(flow_env):
    # Tighten lesson AND MF dump both fire: the sums stack and cap at
    # 0.08 so the gate never becomes unreachable. Defaults: 0.03 +
    # 0.03 = 0.06. A bigger tighten lesson (0.06) would sum to 0.09 ->
    # capped at 0.08.
    _write_flow(flow_env, -6.5e6)
    lessons.refresh_lessons("2026-09-16")
    raw = json.loads(
        (flow_env / "lessons.json").read_text(encoding="utf-8")
    )
    raw["meta"] = {"should_tighten": True}
    raw["applied"] = True
    (flow_env / "lessons.json").write_text(
        json.dumps(raw), encoding="utf-8"
    )
    view = lessons.load_lessons()
    assert view["min_master_score_adjustment"] == pytest.approx(0.06)

    view_capped = lessons.load_lessons(
        {"learning": {"min_gain_for_tightening": 0.06}}
    )
    assert view_capped["min_master_score_adjustment"] == pytest.approx(0.08)
