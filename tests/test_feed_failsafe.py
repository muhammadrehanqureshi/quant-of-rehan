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
        self.assertIn("preopen-ready:", text,
                      "the alert is deduped per day, one email at most")
        self.assertNotIn("schtasks", text)
        self.assertNotIn("while true", text)


if __name__ == "__main__":
    unittest.main()
