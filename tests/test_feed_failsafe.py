"""The fail-safe that makes a refused feed impossible to miss (2026-11-10).

On 2026-11-10 every quote push was refused with a 400 for an hour. The relay
kept answering the index and the OPEN status, the card said NO FEED, and the
only trace was a runner's stdout. These checks pin the three pieces that stop
that from happening silently again: the publisher leaves the refusal behind,
the ops alert turns it into one owner email for the day, and a readiness gate
checks the store before the open.
"""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PublisherLeavesTheRefusalTest(unittest.TestCase):
    def test_a_refused_push_writes_a_flag_and_a_good_push_clears_it(self):
        source = (ROOT / "src" / "data" / "feed_capture.py").read_text(
            encoding="utf-8")
        body = source[source.index("class RelayQuotePublisher"):]
        self.assertIn("REFUSED_FLAG = CAPTURE_DIR / \"relay_refused.flag\"", body)
        self.assertIn("def _note_refused_flag(self, status: int, detail: str)",
                      body)
        self.assertIn("if status >= 400:", body,
                      "a 4xx and a 5xx both leave the flag behind")
        self.assertIn("self._clear_refused_flag()", body,
                      "an accepted push must clear it, so a recovered feed is quiet")

    def test_the_flag_carries_the_relays_own_words(self):
        source = (ROOT / "src" / "data" / "feed_capture.py").read_text(
            encoding="utf-8")
        self.assertIn('"status": status', source)
        self.assertIn('"detail": detail[:400]', source)
        self.assertIn('"at": now_karachi().isoformat()', source)


class OpsAlertReportsTheRefusalTest(unittest.TestCase):
    def test_the_capture_health_pass_reads_the_refusal_flag(self):
        source = (ROOT / "scripts" / "ops_alert.py").read_text(encoding="utf-8")
        self.assertIn('REFUSED = ROOT / "data" / "feed_capture" / '
                      '"relay_refused.flag"', source)
        self.assertIn("def refused_message() -> str:", source)
        self.assertIn("if REFUSED.is_file():", source)
        self.assertIn("send(refused_message())", source)
        self.assertIn("REFUSED.unlink()", source,
                      "one email per refusal, never the same one every run")


class ReadinessGateTest(unittest.TestCase):
    def test_a_readiness_gate_runs_before_the_open(self):
        path = ROOT / ".github" / "workflows" / "preopen-readiness.yml"
        self.assertTrue(path.is_file(), "the pre-open gate must exist")
        text = path.read_text(encoding="utf-8")
        self.assertIn('cron: "45 3 * * 1-5"', text, "08:45 PKT on a trading day")
        self.assertIn('cron: "20 4 * * 1-5"', text, "09:20 PKT, frames must exist")
        self.assertIn("/health", text)
        self.assertIn("/quotes", text)
        self.assertIn('read_json(BASE, "/health", attempts=3)', text,
                      "one busy instant is not an outage: the gate retries")
        self.assertIn("from src.data.relay_http import read_json", text,
                      "the reader names itself, or Cloudflare answers 403")
        self.assertNotIn("urllib.request.urlopen(BASE", text,
                         "a default Python user agent is refused by the edge")
        self.assertIn("after three attempts", text,
                      "the alert states how often the relay was tried")
        self.assertIn("minute < 8 * 60 + 40 or minute > 9 * 60 + 30", text,
                      "a late fire outside the pre-open window does no check")
        self.assertNotIn("owner_email", text,
                         "owner order 2026-11-17: this gate emails nothing")
        self.assertNotIn("preopen-ready:", text,
                         "the readiness email marker is retired")
        self.assertNotIn("schtasks", text)
        self.assertNotIn("while true", text)


class ScanAuditFixesTest(unittest.TestCase):
    """Owner audit 2026-11-23: the drift found in the scheduled windows.

    Each finding is pinned by what the workflow must contain, so a later edit
    cannot quietly restore the defect:

      * the readiness report indexed an empty band list on a closed day and
        failed the run (44800521311, the Friday fire delivered after midnight);
      * the failsafe grid stopped at 15:50 and resumed at 16:05, leaving
        Friday's 14:32 to 16:30 band unwatched for fifteen minutes;
      * the signal push safety net ran Tue-Sat, so Saturday fired and Monday
        morning had no push at all;
      * the budget guard stopped at 15:30, so Friday's second band had no
        budget check.
    """

    def _read(self, name: str) -> str:
        return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")

    def test_the_readiness_report_never_indexes_a_closed_day(self):
        text = self._read("readiness-report.yml")
        guard = text.index("if not bands:")
        self.assertLess(guard, text.index("bands[-1]"),
                        "the empty band guard must run before the band is read")
        # The sentence is one print split over two source lines, so the test
        # reads its two halves rather than a run of text the file never holds.
        self.assertIn("is not a PSX trading", text)
        self.assertIn("no session edge to check", text)

    def test_the_failsafe_watches_the_whole_friday_second_band(self):
        text = self._read("session-failsafe.yml")
        self.assertIn('cron: "55 10 * * 1-5"', text,
                      "15:55 PKT closes the 15:50 to 16:05 hole in Friday's band")
        self.assertNotIn('cron: "0,5,15,25,35,45 11 * * 1-5"', text,
                         "a fire on the hour is the one GitHub drops")

    def test_the_signal_safety_net_runs_on_the_trading_week(self):
        text = self._read("signal-push.yml")
        self.assertIn('cron: "45 3 * * 1-5"', text)
        self.assertNotIn('cron: "45 3 * * 2-6"', text,
                         "2-6 fires on Saturday and skips Monday")

    def test_the_budget_guard_covers_the_friday_second_band(self):
        text = self._read("relay-budget-guard.yml")
        self.assertIn('cron: "0,30 4-11 * * 1-5"', text,
                      "hour 11 UTC is 16:00 and 16:30 PKT")


if __name__ == "__main__":
    unittest.main()
