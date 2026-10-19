"""The latest signal tile: three execution numbers, no metadata.

Owner order 2026-10-19: the tile used to repeat the relay's whole card, header,
Karachi clock, rule narration and all. It now shows the ticker and the three
prices of the signal, and one word for every state that has no signal.

The reader lives in SignalText.java, plain Java with no Android imports, so
the interesting half of this file compiles it with the toolchain's javac and
runs the probe in tests/java. Reading the source proves the console calls it;
running it proves the parser returns the numbers and not the header.

The probe skips, with a stated reason, when this machine has no JDK. The
Android build toolchain in C:/Users/rehan/android-tools carries one, so the
probe runs here; a runner without a JDK reports the skip rather than a pass.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JAVA_DIR = ROOT / "android" / "app" / "src" / "main" / "java" / "pk" / "quantofrehan"
SIGNAL_TEXT = JAVA_DIR / "SignalText.java"
CONSOLE = JAVA_DIR / "MainActivity.java"
PROBE = ROOT / "tests" / "java" / "pk" / "quantofrehan" / "SignalTextProbe.java"


def _toolchain() -> tuple[str, str] | None:
    """(javac, java) from PATH or the documented Android toolchain, or None."""
    on_path = shutil.which("javac")
    if on_path:
        java = shutil.which("java")
        return (on_path, java) if java else None
    for base in (Path("C:/Users/rehan/android-tools"), Path.home() / "android-tools"):
        for javac in sorted(base.glob("jdk-*/bin/javac*")):
            java = javac.with_name("java" + javac.suffix)
            if javac.is_file() and java.is_file():
                return str(javac), str(java)
    return None


class SignalTextSourceTest(unittest.TestCase):
    """The class stays testable, and the console goes through it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.reader = SIGNAL_TEXT.read_text(encoding="utf-8")
        cls.console = CONSOLE.read_text(encoding="utf-8")

    def test_the_reader_is_plain_java(self):
        self.assertNotIn("import android.", self.reader)
        self.assertNotIn("import org.json", self.reader)
        self.assertIn("final class SignalText", self.reader)

    def test_the_console_renders_through_the_reader(self):
        self.assertIn("String text = SignalText.compact(raw);", self.console)
        self.assertIn("SignalText.NO_TRADE.equals(text)", self.console)
        self.assertIn("SignalText.UNAVAILABLE.equals(text)", self.console)
        # The old inline parser is gone, so there is one place the rules live.
        for retired in ("valueAfterLabel(", "leadingPriceOrNull(", "knownOrReported("):
            with self.subTest(retired=retired):
                self.assertNotIn(retired, self.console)

    def test_the_two_word_states_come_from_string_resources(self):
        strings = (ROOT / "android" / "app" / "src" / "main" / "res" / "values"
                   / "strings.xml").read_text(encoding="utf-8")
        self.assertIn("getString(R.string.signal_none)", self.console)
        self.assertIn("getString(R.string.signal_unavailable)", self.console)
        self.assertIn('name="signal_none"', strings)
        self.assertIn('name="signal_unavailable"', strings)

    def test_the_tile_carries_no_metadata(self):
        """No date, no clock and no rule narration, in the code that ships."""
        after_doc = self.reader.split("*/", 1)[1]
        for banned in ("QoR intraday", "PKT", "formatDate", "DateTime"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, after_doc)


@unittest.skipUnless(_toolchain(), "no JDK on this machine to run the JVM probe")
class SignalTextBehaviourTest(unittest.TestCase):
    """The parsed output, executed rather than read."""

    def test_the_reader_behaves_on_the_jvm(self):
        javac, java = _toolchain()
        with tempfile.TemporaryDirectory() as out:
            build = subprocess.run(
                [javac, "-encoding", "UTF-8", "-d", out,
                 str(SIGNAL_TEXT), str(PROBE)],
                capture_output=True, text=True)
            self.assertEqual(build.returncode, 0,
                             f"the reader did not compile:\n{build.stderr}")
            run = subprocess.run(
                [java, "-cp", out, "pk.quantofrehan.SignalTextProbe"],
                capture_output=True, text=True)
            self.assertEqual(run.returncode, 0,
                             f"the probe failed:\n{run.stdout}\n{run.stderr}")
            self.assertIn("PASS SignalText", run.stdout)


if __name__ == "__main__":
    unittest.main()
