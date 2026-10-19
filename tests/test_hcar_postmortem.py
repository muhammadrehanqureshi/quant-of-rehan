from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.research import hcar_postmortem as audit  # noqa: E402
from src.signals import momentum_scanner as scanner  # noqa: E402


class CandidateAuditTests(unittest.TestCase):
    @staticmethod
    def observation(slot: str, symbol: str, entry: float, reason: str) -> dict:
        return {"slot": slot, "snapshot": {
            "reason": reason,
            "observed_candidate": {
                "symbol": symbol, "score": 60.0,
                "price": {"last": entry},
            },
        }}

    @staticmethod
    def sample(trade_at: str, last: float, observed_at: str | None = None) -> dict:
        trade = datetime.fromisoformat(f"2026-10-16T{trade_at}:00+05:00")
        observed = datetime.fromisoformat(
            f"2026-10-16T{observed_at or trade_at}:00+05:00")
        return {"trade_at": trade, "observed_at": observed, "last": last}

    def test_broker_samples_below_target_never_claim_daily_high_result(self):
        observations = [self.observation("15:07", "ISL", 79.48,
                                         "candidate was observed and refused")]
        row, = audit.audit_rejected(
            observations, {"ISL": [self.sample("15:09", 80.0)]}, "2026-10-16",
            observation_slots={"15:07"})
        self.assertEqual(row.target_price, 81.0696)
        self.assertEqual(row.classification, "BROKER_TAPE_NO_TARGET_PRINT_OBSERVED")
        self.assertEqual(row.highest_observed_trade, 80.0)
        self.assertEqual(row.source, "locally saved broker MKT-FEED")

    def test_post_refusal_broker_print_at_target_is_confirmed(self):
        observations = [self.observation("16:02", "AGP", 163.0,
                                         "candidate was observed and refused")]
        row, = audit.audit_rejected(
            observations, {"AGP": [self.sample("16:03", 166.26)]}, "2026-10-16",
            observation_slots={"16:02"})
        self.assertEqual(row.classification, "BROKER_TAPE_CONFIRMED_TP_PRINT")
        self.assertEqual(row.first_post_refusal_trade, "2026-10-16T16:03:00+05:00")

    def test_run_includes_same_day_local_observation_and_filters_candidates_by_slot(self):
        import pandas as pd
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = root / "capture.ndjson"
            capture.write_text("", encoding="utf-8")
            cache = root / "observation.json"
            cache.write_text(json.dumps({
                "date": "2026-10-16", "slot": "15:07",
                "reason": "candidate observed and refused",
                "observed_candidate": {
                    "symbol": "ISL", "score": 60.0,
                    "price": {"last": 79.48},
                },
            }), encoding="utf-8")
            frame = pd.DataFrame([{
                "date": pd.Timestamp("2026-10-01"), "symbol": "HCAR",
                "open": 100.0, "high": 102.0, "low": 99.0,
                "close": 101.0, "volume": 1000,
            }])
            observed_payload = [{
                "slot": "15:07", "snapshot": {
                    "reason": "observed and refused",
                    "observed_candidate": {"symbol": "ISL", "score": 60.0,
                                           "price": {"last": 79.48}},
                },
            }]
            broker_rows = {"ISL": [self.sample("15:09", 80.0)]}
            journal = root / "journal.jsonl"
            journal.write_text(json.dumps({"date": "2026-10-16", "symbol": "HCAR",
                                           "entry": 203.0, "target_hit": False,
                                           "outcome": "CLOSED_AT_SESSION_END"}) + "\n",
                               encoding="utf-8")
            original_postmortem = audit.hcar_postmortem
            with patch.object(audit, "_date_observations", return_value=observed_payload), \
                 patch.object(audit, "hcar_postmortem", side_effect=lambda *args: original_postmortem(*args)), \
                 patch.object(audit, "_relay_json", return_value={"sessions": []}), \
                 patch.object(audit, "_broker_tick_samples", return_value=(
                     broker_rows, {"last_snapshot": "2026-10-16T16:00:00+05:00"})), \
                 patch.object(audit.pd, "read_csv", return_value=frame), \
                 patch.object(audit, "hcar_daily_backtest", return_value={"data": {}}):
                result = audit.run("2026-10-16", capture, root / "daily.csv",
                                   root / "report.json", observation_cache=cache,
                                   session_journal=journal)
            self.assertEqual(result["candidate_count"], 1)
            self.assertEqual(result["refusal_observation_count"], 2)
            self.assertEqual(result["candidate_outcomes"][0]["repeated_refusals"], 2)
            self.assertEqual(result["candidate_outcomes"][0]["classification"],
                             "BROKER_TAPE_NO_TARGET_PRINT_OBSERVED")
            self.assertEqual(result["hcar"]["recorded_outcome"],
                             "CLOSED_AT_SESSION_END")
            self.assertEqual(result["hcar"]["target_hit"], False)
            self.assertEqual(result["hcar"]["entry_price"], 203.0)
            self.assertEqual(result["evidence"]["candidate_observation_slots"], 1)
            self.assertEqual(result["evidence"]["relay_observation_records"], 0)
            self.assertTrue(result["evidence"]["local_observation_appended"])
            self.assertEqual(json.loads((root / "report.json").read_text(encoding="utf-8")), result)

    def test_refusal_minute_is_excluded_as_time_order_is_ambiguous(self):
        observations = [self.observation("15:07", "ISL", 79.48,
                                         "candidate was observed and refused")]
        row, = audit.audit_rejected(
            observations, {"ISL": [self.sample("15:07", 81.10)]}, "2026-10-16",
            observation_slots={"15:07"})
        self.assertEqual(row.classification, "UNVERIFIED_NO_POST_REFUSAL_BROKER_DATA")

    def test_after_hours_print_is_not_counted_as_a_session_target_touch(self):
        observations = [self.observation("16:02", "AGP", 163.0,
                                         "candidate was observed and refused")]
        row, = audit.audit_rejected(
            observations, {"AGP": [self.sample("16:31", 170.0)]}, "2026-10-16",
            observation_slots={"16:02"})
        self.assertEqual(row.classification, "UNVERIFIED_NO_POST_REFUSAL_BROKER_DATA")

    def test_invalid_candidate_entry_is_unverified_not_a_target_hit(self):
        observations = [self.observation("15:07", "ISL", float("nan"),
                                         "candidate was observed and refused")]
        row, = audit.audit_rejected(
            observations, {"ISL": [self.sample("15:09", 81.10)]}, "2026-10-16",
            observation_slots={"15:07"})
        self.assertIsNone(row.entry_reference)
        self.assertIsNone(row.target_price)
        self.assertEqual(row.classification, "UNVERIFIED_NO_ENTRY_REFERENCE")

    def test_first_refusal_is_chronological_not_lexical(self):
        observations = [
            self.observation("9:59", "STL", 22.70,
                             "candidate observed and refused"),
            self.observation("10:02", "STL", 22.72,
                             "candidate observed and refused"),
        ]
        row, = audit.audit_rejected(
            observations, {"STL": [self.sample("10:00", 23.20)]}, "2026-10-16",
            observation_slots={"9:59", "10:02"})
        self.assertEqual(row.first_refusal_slot, "9:59")
        self.assertEqual(row.entry_reference, 22.70)

    def test_capture_ending_before_refusal_is_explicitly_unverified(self):
        observations = [self.observation("15:07", "ISL", 79.48,
                                         "candidate was observed and refused")]
        end = datetime.fromisoformat("2026-10-16T12:34:44+05:00")
        row, = audit.audit_rejected(observations, {}, "2026-10-16", capture_last=end,
                                    observation_slots={"15:07"})
        self.assertEqual(row.classification, "UNVERIFIED_NO_POST_REFUSAL_BROKER_DATA")
        self.assertIn("capture ended before", row.evidence)

    def test_ignores_ranked_candidates_unless_explicitly_refused(self):
        row = {"slot": "10:00", "snapshot": {
            "reason": "market condition", "ranked_top": [{"symbol": "HCAR"}]}}
        self.assertEqual(audit.audit_rejected([row], {}, "2026-10-16",
                                              observation_slots=set()), [])

    def test_repeated_loop_refusals_collapse_to_first_candidate(self):
        observations = [
            self.observation("15:10", "STL", 22.70,
                             "candidate observed and refused"),
            self.observation("15:11", "STL", 22.72,
                             "candidate observed and refused"),
        ]
        row, = audit.audit_rejected(
            observations, {"STL": [self.sample("15:12", 22.84)]}, "2026-10-16",
            observation_slots={"15:10", "15:11"})
        self.assertEqual(row.first_refusal_slot, "15:10")
        self.assertEqual(row.entry_reference, 22.70)
        self.assertEqual(row.repeated_refusals, 2)
        self.assertEqual(row.classification, "BROKER_TAPE_NO_TARGET_PRINT_OBSERVED")


class BrokerCaptureTests(unittest.TestCase):
    def test_extracts_trade_timestamped_rows_and_capture_coverage(self):
        lines = [
            {"kind": "MKT-FEED", "ts": "2026-10-16T15:09:30+05:00", "ticks": [
                {"scrip": "ISL:REG", "tick_time": "15:08:45", "last": "80.00"},
                {"scrip": "AGP:REG", "tick_time": "15:09:05", "last": "166.00"},
            ]},
            {"kind": "MKT-STATS", "ts": "2026-10-16T15:10:00+05:00", "ticks": [
                {"scrip": "ISL", "tick_time": "15:09:50", "last": "999.00"},
            ]},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.ndjson"
            with path.open("w", encoding="utf-8") as handle:
                for line in lines:
                    handle.write(json.dumps(line) + "\n")
            samples, coverage = audit._broker_tick_samples(path, "2026-10-16")
        self.assertEqual(set(samples), {"ISL", "AGP"})
        self.assertEqual(samples["ISL"][0]["last"], 80.0)
        self.assertEqual(coverage["tick_rows_with_valid_trade_time"], 2)
        self.assertEqual(coverage["source"],
                         "locally saved broker MKT-FEED tape, timestamped last-trade prints")


class ConfirmationTests(unittest.TestCase):
    def test_wilder_rsi_known_increasing_series_is_100(self):
        self.assertEqual(audit._wilder_rsi([float(i) for i in range(1, 16)]), 100.0)

    def test_rsi_requires_sufficient_finite_positive_prices(self):
        self.assertIsNone(audit._wilder_rsi([1.0] * 14))
        self.assertIsNone(audit._wilder_rsi([1.0] * 14 + [float("nan")]))

    def test_non_finite_metrics_are_json_null(self):
        import json

        safe = audit._json_safe({"positive_only_profit_factor": float("inf"),
                                 "nested": [float("nan"), 1.0]})
        self.assertEqual(safe, {"positive_only_profit_factor": None,
                                "nested": [None, 1.0]})
        self.assertEqual(json.loads(json.dumps(safe, allow_nan=False)), safe)

    def test_hcar_backtest_positions_are_independent_of_unrelated_panel_rows(self):
        import pandas as pd

        dates = pd.bdate_range("2025-01-01", periods=60)
        rows = []
        for index, day in enumerate(dates):
            close = 100.0 + index * 0.1 + 0.005 * index * index
            prior = index - 1
            open_price = (close if index == 0 else
                          100.0 + prior * 0.1 + 0.005 * prior * prior)
            rows.append({"date": day, "symbol": "HCAR", "open": open_price,
                         "high": close + 0.1, "low": open_price - 0.1,
                         "close": close, "volume": 1000 + index * 10})

        solo = audit.hcar_daily_backtest(pd.DataFrame(rows))
        panel = pd.DataFrame([
            row if symbol == "HCAR" else {**row, "symbol": "OTHER"}
            for row in rows
            for symbol in ("HCAR", "OTHER")
        ])
        interleaved = audit.hcar_daily_backtest(panel)

        for strategy in ("baseline", "confirmation_only", "improved"):
            self.assertEqual(
                solo[strategy]["summary"]["n_trades"],
                interleaved[strategy]["summary"]["n_trades"],
            )
            self.assertEqual(
                solo[strategy]["summary"]["n_signals_skipped"],
                interleaved[strategy]["summary"]["n_signals_skipped"],
            )

    def test_reconstructs_premarket_limited_hcar_signal_time_bars(self):
        from src.data.sessions import KARACHI

        day = "2026-10-16"
        opens = datetime.fromisoformat(f"{day}T10:00:00+05:00")
        target_file = None
        with tempfile.TemporaryDirectory() as directory:
            target_file = Path(directory) / "hcar.ndjson"
            with target_file.open("w", encoding="utf-8") as handle:
                # 16 valid single-symbol tape rows, enough for an RSI-14.
                volume = 100
                for index in range(16):
                    minute = opens + timedelta(minutes=index)
                    price = 100.0 + index * 0.1
                    volume += 10
                    handle.write(
                        '{"kind":"MKT-FEED","ts":"%s","ticks":[{"scrip":"HCAR:REG","last":"%.2f","volume":"%d","tick_time":"%s","high":"%.2f","low":"%.2f","trades":"%d"}]}\n'
                        % (minute.isoformat(), price, volume,
                           minute.strftime("%H:%M:%S"), price, price, index + 1))
            result = audit.hcar_postmortem(
                target_file, day, "10:16", [{"slot": "10:00", "snapshot": {
                    "candidate": {"symbol": "HCAR", "price": {"last": 101.5}}}}],
                [{"date": day, "symbol": "HCAR",
                                                "entry": 101.5,
                                                "target_hit": False,
                                                "outcome": "CLOSED_AT_SESSION_END"}])
        self.assertEqual(result["pre_signal"]["bars"], 16)
        self.assertEqual(result["pre_signal"]["rsi14_wilder"], 100.0)
        self.assertTrue(result["pre_signal"]["capture_starts_after_open"])
        self.assertEqual(result["target_price"], 103.53)


if __name__ == "__main__":
    unittest.main()
