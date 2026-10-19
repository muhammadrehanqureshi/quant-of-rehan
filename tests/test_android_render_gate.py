"""RenderGate: the decision that keeps an unchanged answer off the screen.

The console polls once a second while the market is live, but most answers are
identical to the one before them, and a repaint of an identical answer is a
whole-tile measure, layout and draw per second for no visible change. The
gate compares the answer with the one already painted and skips that work.

Two kinds of check live here, because they catch different mistakes:

  * the source contract below proves the console actually asks the gate, and
    asks it again after a resume, which is the case a skip would otherwise
    turn into a frozen status light;
  * the JVM probe compiles the real RenderGate and exercises its decisions,
    because a comparison that always returns true (or always false) passes any
    amount of reading and fails here.

The probe skips, with a stated reason, when this machine has no javac. The
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
GATE = JAVA_DIR / "RenderGate.java"
CONSOLE = JAVA_DIR / "MainActivity.java"
PROBE = ROOT / "tests" / "java" / "pk" / "quantofrehan" / "RenderGateProbe.java"


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


class RenderGateSourceTest(unittest.TestCase):
    """The console asks the gate, in both places that matter."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.gate = GATE.read_text(encoding="utf-8")
        cls.console = CONSOLE.read_text(encoding="utf-8")

    def test_the_gate_is_plain_java(self):
        """It must stay testable on the JVM, so it imports nothing from Android."""
        self.assertNotIn("import android.", self.gate)
        self.assertNotIn("import org.json", self.gate)
        self.assertIn("final class RenderGate", self.gate)

    def test_the_console_paints_through_the_gate(self):
        self.assertIn("private final RenderGate renderGate = new RenderGate();",
                      self.console)
        render = self.console[self.console.index("private void render(boolean online"):]
        render = render[:render.index("private void paint(")]
        self.assertIn("renderGate.changed(online, d, s, marketFingerprint(market))",
                      render)
        # The cadence is still re-decided on EVERY answer, painted or not:
        # skipping the paint must never skip the scheduling point.
        self.assertLess(render.index("renderGate.changed("),
                        render.index("marketOpenSeen = online;"))
        self.assertIn("scheduleNext();", render)

    def test_a_resumed_console_repaints(self):
        """onPause stops the breath; a skipped paint on resume would freeze it."""
        resume = self.console[self.console.index("protected void onResume()"):]
        resume = resume[:resume.index("protected void onPause()")]
        self.assertIn("renderGate.reset();", resume)


@unittest.skipUnless(_toolchain(), "no JDK on this machine to run the JVM probe")
class RenderGateBehaviourTest(unittest.TestCase):
    """The decided behaviour, executed rather than read."""

    def test_the_gate_behaves_on_the_jvm(self):
        javac, java = _toolchain()
        with tempfile.TemporaryDirectory() as out:
            build = subprocess.run(
                [javac, "-encoding", "UTF-8", "-d", out, str(GATE), str(PROBE)],
                capture_output=True, text=True)
            self.assertEqual(build.returncode, 0,
                             f"the gate did not compile:\n{build.stderr}")
            run = subprocess.run(
                [java, "-cp", out, "pk.quantofrehan.RenderGateProbe"],
                capture_output=True, text=True)
            self.assertEqual(run.returncode, 0,
                             f"the probe failed:\n{run.stdout}\n{run.stderr}")
            self.assertIn("PASS RenderGate", run.stdout)


if __name__ == "__main__":
    unittest.main()
