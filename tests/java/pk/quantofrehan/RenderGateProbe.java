package pk.quantofrehan;

import java.util.ArrayList;
import java.util.List;

/**
 * Runs RenderGate on the JVM.
 *
 * The Android source tests read Java as text, which cannot tell a correct
 * comparison from one that always returns true. This probe compiles the gate
 * with the toolchain's javac and exercises the decisions the console relies
 * on, so "an identical answer is not repainted" is measured rather than read.
 *
 * Exit code 0 when every case passes, 1 with the failing case named otherwise.
 */
public final class RenderGateProbe {

    private static final List<String> failures = new ArrayList<>();

    private RenderGateProbe() {
    }

    public static void main(String[] args) {
        firstAnswerIsAlwaysAPaint();
        identicalAnswerIsNotRepainted();
        aNullFieldReadsAsEmpty();
        everyFieldCanTriggerAPaint();
        goingBackToAnEarlierValueIsAPaint();
        resetForcesOneRepaint();
        skippedAnswersDoNotAdvanceTheStoredState();

        if (failures.isEmpty()) {
            System.out.println("PASS RenderGate: 7 cases");
            return;
        }
        for (String failure : failures) {
            System.out.println("FAIL " + failure);
        }
        System.exit(1);
    }

    private static void firstAnswerIsAlwaysAPaint() {
        RenderGate gate = new RenderGate();
        check("a fresh gate paints its first answer",
                gate.changed(true, "Karachi: 09:32 PKT", "NO TRADE", 7));
    }

    private static void identicalAnswerIsNotRepainted() {
        RenderGate gate = new RenderGate();
        gate.changed(true, "Karachi: 09:32 PKT", "NO TRADE", 7);
        check("an identical answer is skipped",
                !gate.changed(true, "Karachi: 09:32 PKT", "NO TRADE", 7));
        check("a second identical answer is skipped too",
                !gate.changed(true, "Karachi: 09:32 PKT", "NO TRADE", 7));
    }

    private static void aNullFieldReadsAsEmpty() {
        RenderGate gate = new RenderGate();
        check("null detail paints first", gate.changed(false, null, null, 0));
        check("null and empty detail are the same answer",
                !gate.changed(false, "", "", 0));
    }

    private static void everyFieldCanTriggerAPaint() {
        RenderGate gate = new RenderGate();
        gate.changed(true, "d", "s", 1);
        check("a changed online flag repaints", gate.changed(false, "d", "s", 1));
        check("a changed detail repaints", gate.changed(false, "d2", "s", 1));
        check("changed signals repaint", gate.changed(false, "d2", "s2", 1));
        check("a changed market repaints", gate.changed(false, "d2", "s2", 2));
    }

    private static void goingBackToAnEarlierValueIsAPaint() {
        RenderGate gate = new RenderGate();
        gate.changed(true, "a", "x", 1);
        gate.changed(true, "b", "x", 1);
        check("a value returning to its earlier text repaints",
                gate.changed(true, "a", "x", 1));
    }

    private static void resetForcesOneRepaint() {
        RenderGate gate = new RenderGate();
        gate.changed(true, "d", "s", 3);
        gate.reset();
        check("a resumed console repaints the answer it already had",
                gate.changed(true, "d", "s", 3));
        check("and skips the one after it",
                !gate.changed(true, "d", "s", 3));
    }

    private static void skippedAnswersDoNotAdvanceTheStoredState() {
        RenderGate gate = new RenderGate();
        gate.changed(true, "a", "s", 1);
        gate.changed(true, "a", "s", 1);          // skipped, must change nothing
        check("a skipped answer leaves the stored answer alone",
                gate.changed(true, "b", "s", 1));
    }

    private static void check(String what, boolean ok) {
        if (!ok) {
            failures.add(what);
        }
    }
}
