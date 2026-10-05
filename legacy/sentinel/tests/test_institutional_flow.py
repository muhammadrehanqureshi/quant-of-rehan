"""
Tests for the institutional-flow layer.

v4.0.0: the upstream fetcher (psxterminal.com FIPI table scraper) is
RETIRED - the ECLEAR broker feed is the sole market-data source and it
does not carry the investor-matrix. The stored history file
(data/foreign_flow_history.jsonl) is kept and remains advisory-only:
market_regime.institutional_state, append_foreign_flow_history and the
Rule 12 / 12b engine paths all read stored rows and are unchanged.

Covers:
  * the retirement rails (import-time and call-time failure mode);
  * market_regime.institutional_state: foreign/retail/institutional
    reads, retail-FOMO and smart-retail-war signatures, legacy rows,
    the v2.5.2 war-magnitude floors;
  * market_regime.append_foreign_flow_history: record shape, idempotent
    replacement, legacy-shape fallback;
  * decision_engine Rule 12b: war blocks, fomo advisory, dormant
    without history; Rule 12 advisory-only (v0.14.1).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from psx_core import paths

import market_regime
from decision_engine import DecisionConfig, DecisionEngine


# ---------------------------------------------------------------------------
# Retirement rails
# ---------------------------------------------------------------------------


class TestFetcherRetired:
    def test_module_import_raises(self):
        # The fetcher module is deleted; anything still importing it
        # (stale call sites, notebooks) must fail loudly, not scrape a
        # dead site.
        with pytest.raises(ImportError):
            import fetch_foreign_flow  # noqa: F401

    def test_corporate_actions_fetcher_raises_retired(self):
        import corporate_actions

        with pytest.raises(corporate_actions.RetiredSource):
            corporate_actions.fetch_corporate_actions()


# ---------------------------------------------------------------------------
# institutional_state
# ---------------------------------------------------------------------------


def _row(date, inv_map):
    by = {
        name: {"buy": 0.0, "sell": 0.0, "net": net}
        for name, net in inv_map.items()
    }
    return {
        "date": date,
        "net_total_usd": by["Foreign"]["net"],
        "byInvestor": by,
    }


class TestInstitutionalState:
    def test_reads_latest_session(self):
        rows = [
            _row("2026-09-10", {"Foreign": -1e6, "Individuals": 2e6}),
            _row("2026-09-11", {"Foreign": -6.4e6, "Individuals": 4.9e6}),
        ]
        st = market_regime.institutional_state(rows)
        assert st["foreign_net_usd"] == pytest.approx(-6.4e6)
        assert st["retail_net_usd"] == pytest.approx(4.9e6)
        assert st["institutional_net_usd"] == pytest.approx(-6.4e6)
        assert st["sessions"] == 2

    def test_legacy_rows_fall_back_to_total(self):
        rows = [{"date": "2026-09-10", "net_total_usd": -1_500_000.0}]
        st = market_regime.institutional_state(rows)
        assert st["foreign_net_usd"] == pytest.approx(-1_500_000.0)
        assert st["retail_fomo"] is False
        assert st["smart_retail_war"] is False

    def test_war_signature_blocks(self):
        # Institutions selling 3x harder than retail buys.
        rows = [
            _row(
                "2026-09-11",
                {"Foreign": -10e6, "Mutual Funds": -3e6, "Individuals": 4e6},
            )
        ]
        st = market_regime.institutional_state(rows)
        assert st["smart_retail_war"] is True

    def test_mild_divergence_is_not_war(self):
        rows = [
            _row(
                "2026-09-11",
                {"Foreign": -1e6, "Mutual Funds": 0.0, "Individuals": 4e6},
            )
        ]
        st = market_regime.institutional_state(rows)
        assert st["smart_retail_war"] is False

    def test_retail_fomo_needs_baseline_jump(self):
        # Retail buys far above its recent norm.
        rows = [
            _row("2026-09-08", {"Individuals": 0.5e6, "Foreign": 0.0}),
            _row("2026-09-09", {"Individuals": 0.5e6, "Foreign": 0.0}),
            _row("2026-09-10", {"Individuals": 0.5e6, "Foreign": 0.0}),
            _row("2026-09-11", {"Individuals": 5e6, "Foreign": -1e6}),
        ]
        st = market_regime.institutional_state(rows)
        assert st["retail_fomo"] is True

    def test_no_rows_is_all_unknown(self):
        st = market_regime.institutional_state([])
        assert st["foreign_net_usd"] is None
        assert st["retail_fomo"] is False
        assert st["smart_retail_war"] is False


# ---------------------------------------------------------------------------
# History persistence
# ---------------------------------------------------------------------------


class TestAppendHistory:
    def test_record_shape_and_idempotence(self, tmp_path, monkeypatch):
        monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
        snap = {
            "netByInvestorUsd": {
                "Foreign": {"buy": 1.0, "sell": 2.0, "net": -1e6},
                "Individuals": {"buy": 2.0, "sell": 1.0, "net": 1e6},
            },
            "netMatrixUsd": {"Foreign": {"Cement": -1e6}},
        }
        assert market_regime.append_foreign_flow_history(snap, "2026-09-11")
        # Same date again: replace, not duplicate.
        assert market_regime.append_foreign_flow_history(snap, "2026-09-11")
        lines = [
            json.loads(ln)
            for ln in (tmp_path / "foreign_flow_history.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if ln.strip()
        ]
        assert len(lines) == 1
        rec = lines[0]
        assert rec["net_total_usd"] == pytest.approx(-1e6)
        assert rec["byInvestor"]["Foreign"]["net"] == pytest.approx(-1e6)
        assert rec["matrix"]["Foreign"]["Cement"] == pytest.approx(-1e6)

    def test_legacy_snapshot_uses_sector_sum(self, tmp_path, monkeypatch):
        monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
        snap = {"foreignNetBySectorUsd": {"Cement": -2e6, "Banks": 1e6}}
        assert market_regime.append_foreign_flow_history(snap, "2026-09-10")
        rec = json.loads(
            (tmp_path / "foreign_flow_history.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()[0]
        )
        assert rec["net_total_usd"] == pytest.approx(-1e6)
        assert "byInvestor" not in rec

    def test_empty_snapshot_is_noop(self, tmp_path, monkeypatch):
        monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
        assert not market_regime.append_foreign_flow_history({}, "2026-09-10")
        assert not (tmp_path / "foreign_flow_history.jsonl").exists()


# ---------------------------------------------------------------------------
# Engine Rule 12b
# ---------------------------------------------------------------------------


class TestRule12bInstitutional:
    """
    Rule 12b fires inside evaluate() right after the foreign-flow gate
    and before candidate filtering - so a war context blocks ANY frame,
    and a dormant context (no history) never mentions it.
    """

    def _context(self, **fields):
        class Ctx:
            pass

        for key, value in fields.items():
            setattr(Ctx, key, value)
        return Ctx()

    def _frame(self):
        # The full feature fixture from the engine test suite: deep
        # enough for evaluate() to run its whole gate chain.
        from test_decision_engine import (
            _add_confirmation_columns,
            _add_horse_columns,
            _make_feature_frame,
        )

        df = _add_horse_columns(_make_feature_frame())
        return _add_confirmation_columns(df)

    def test_war_blocks_entry(self):
        eng = DecisionEngine(
            DecisionConfig(institutional_flow_enabled=True),
        )
        ctx = self._context(
            foreign_flow_blocked=False,
            inst_smart_retail_war=True,
            inst_foreign_net_usd=-13e6,
            inst_retail_net_usd=4e6,
            inst_institutional_net_usd=-13e6,
            inst_retail_fomo=False,
        )
        decision = eng.evaluate(self._frame(), context=ctx)
        assert decision.action == "STAND_ASIDE"
        assert "Rule 12b" in decision.reason
        assert decision.metadata["regime"]["inst_smart_retail_war"] is True

    def test_dormant_without_history(self):
        eng = DecisionEngine(
            DecisionConfig(institutional_flow_enabled=True),
        )
        ctx = self._context(foreign_flow_blocked=False)
        decision = eng.evaluate(self._frame(), context=ctx)
        assert "Rule 12b" not in decision.reason

    def test_fomo_is_advisory_only(self):
        eng = DecisionEngine(
            DecisionConfig(institutional_flow_enabled=True),
        )
        ctx = self._context(
            foreign_flow_blocked=False,
            inst_smart_retail_war=False,
            inst_retail_fomo=True,
            inst_foreign_net_usd=-1e6,
        )
        decision = eng.evaluate(self._frame(), context=ctx)
        assert "Rule 12b" not in decision.reason

    def test_disabled_by_config(self):
        eng = DecisionEngine(
            DecisionConfig(institutional_flow_enabled=False),
        )
        ctx = self._context(
            foreign_flow_blocked=False,
            inst_smart_retail_war=True,
        )
        decision = eng.evaluate(self._frame(), context=ctx)
        assert "Rule 12b" not in decision.reason


# Rule 12 demoted to advisory (v0.14.1)
# -------------------------------------
# 2026-09-15: the hard veto blocked every cycle of a +1700-point rally
# on a 3-session selling tail (-292k / -6.4M / -651k). Every rally day
# in the stored history was a foreign-net-selling day. Flow data lags
# the tape; the tape decides. These tests pin that.


class TestRuleTwelveAdvisoryOnly:
    """Rule 12 reads and reports but never vetoes."""

    def _context(self, **fields):
        class Ctx:
            pass

        for key, value in fields.items():
            setattr(Ctx, key, value)
        return Ctx()

    def _frame(self):
        from test_decision_engine import (
            _add_confirmation_columns,
            _add_horse_columns,
            _make_feature_frame,
        )

        df = _add_horse_columns(_make_feature_frame())
        return _add_confirmation_columns(df)

    def test_blocked_flow_does_not_veto(self):
        """The 2026-09-15 scenario: sell-off signature + healthy frame
        must still be allowed to trade."""
        eng = DecisionEngine(DecisionConfig())
        ctx = self._context(
            foreign_flow_blocked=True,
            foreign_flow_streak=3,
            foreign_flow_sum_usd=-7.34e6,
            inst_smart_retail_war=False,
        )
        decision = eng.evaluate(self._frame(), context=ctx)
        assert "Rule 12" not in decision.reason

    def test_flow_rides_in_metadata(self):
        """The advisory read is surfaced on the decision for display."""
        eng = DecisionEngine(DecisionConfig())
        ctx = self._context(
            foreign_flow_blocked=True,
            foreign_flow_streak=3,
            foreign_flow_sum_usd=-7.34e6,
        )
        decision = eng.evaluate(self._frame(), context=ctx)
        regime = decision.metadata["regime"]
        assert regime["foreign_flow_streak"] == 3
        assert regime["foreign_flow_advisory_only"] is True

    def test_advisory_property(self):
        eng = DecisionEngine(DecisionConfig())
        ctx = self._context(
            foreign_flow_blocked=True,
            foreign_flow_streak=3,
            foreign_flow_sum_usd=-7.34e6,
        )
        adv = eng.foreign_flow_advisory(ctx)
        assert adv == {
            "foreign_flow_streak": 3,
            "foreign_flow_sum_usd": -7.34e6,
            "foreign_flow_blocked": True,
            "advisory": True,
        }
        assert eng.foreign_flow_advisory(None) is None

    def test_no_context_still_trades(self):
        eng = DecisionEngine(DecisionConfig())
        decision = eng.evaluate(self._frame(), context=None)
        assert "Rule 12" not in decision.reason


# ---------------------------------------------------------------------------
# v2.5.2 - war magnitude floors (the Sep-23 all-day noise veto)
# ---------------------------------------------------------------------------


class TestWarMagnitudeFloors:
    """
    Sep 23, 2026: the whole session was vetoed by a "-2.2M inst vs
    +0.3M retail" divergence - rounding error on PSX volume, the same
    lagging-flow-kills-a-rally misfire the v0.14.1 lesson documented.
    The war signature now requires real size: institutions must dump
    >= war_min_side_usd ($10M default) and retail must absorb
    >= war_min_retail_usd ($1M default).
    """

    def _row(self, inst_net, retail_net):
        # Split inst_net across the institutional classes; the
        # aggregate is what institutional_state() computes.
        return {
            "date": "2026-09-23",
            "byInvestor": {
                "Foreign": {"net": 1.2e6},
                "Individuals": {"net": retail_net},
                "Banks / DFI": {"net": inst_net * 0.6},
                "Insurance": {"net": inst_net * 0.4},
                "Mutual Funds": {"net": 0.0},
                "Brokers": {"net": 0.0},
                "Companies": {"net": 0.0},
                "NBFC": {"net": 0.0},
                "Others": {"net": 0.0},
            },
        }

    def test_sep23_noise_is_not_a_war(self):
        from market_regime import institutional_state

        state = institutional_state(
            [self._row(-2.17e6, 0.346e6)],
        )
        assert state["smart_retail_war"] is False

    def test_real_war_still_fires(self):
        from market_regime import institutional_state

        state = institutional_state([self._row(-24e6, 8e6)])
        assert state["smart_retail_war"] is True

    def test_dump_without_retail_absorption_is_not_a_war(self):
        from market_regime import institutional_state

        state = institutional_state([self._row(-12e6, 0.4e6)])
        assert state["smart_retail_war"] is False

    def test_engine_guard_blocks_stale_context_veto(self):
        # Belt and braces: even if a stale context claims war=True
        # with sub-floor nets, the engine refuses to veto the session.
        class Ctx:
            foreign_flow_blocked = False
            inst_smart_retail_war = True
            inst_foreign_net_usd = 1.2e6
            inst_retail_net_usd = 0.346e6
            inst_institutional_net_usd = -2.17e6
            inst_retail_fomo = False

        from test_decision_engine import (
            _add_confirmation_columns,
            _add_horse_columns,
            _make_feature_frame,
        )

        df = _add_confirmation_columns(
            _add_horse_columns(_make_feature_frame())
        )
        eng = DecisionEngine(DecisionConfig())
        decision = eng.evaluate(df, context=Ctx())
        assert "Rule 12b" not in decision.reason

    def test_engine_guard_still_vetoes_real_war(self):
        class Ctx:
            foreign_flow_blocked = False
            inst_smart_retail_war = True
            inst_foreign_net_usd = -5e6
            inst_retail_net_usd = 8e6
            inst_institutional_net_usd = -24e6
            inst_retail_fomo = False

        from test_decision_engine import (
            _add_confirmation_columns,
            _add_horse_columns,
            _make_feature_frame,
        )

        df = _add_confirmation_columns(
            _add_horse_columns(_make_feature_frame())
        )
        eng = DecisionEngine(DecisionConfig())
        decision = eng.evaluate(df, context=Ctx())
        assert decision.action == "STAND_ASIDE"
        assert "Rule 12b" in decision.reason
