package pk.quantofrehan;

import java.util.ArrayList;
import java.util.List;

/**
 * Runs SignalText on the JVM against the cards the runner actually writes.
 *
 * The Android source tests can only read Java as text, which cannot tell a
 * parser that returns the three prices from one that returns the header. This
 * probe compiles the real class and checks both card shapes, the no-trade
 * state, and the absences the owner ordered: no date, no clock, no rule
 * narration and no session header in the tile.
 *
 * Exit code 0 when every case passes, 1 with the failing case named otherwise.
 */
public final class SignalTextProbe {

    private static final List<String> failures = new ArrayList<>();

    private SignalTextProbe() {
    }

    public static void main(String[] args) {
        fieldCard();
        sentenceCard();
        noTradeCard();
        missingCard();
        summaryTargetIsNotAPrice();
        metadataNeverLeaks();

        if (failures.isEmpty()) {
            System.out.println("PASS SignalText: 6 cases");
            return;
        }
        for (String failure : failures) {
            System.out.println("FAIL " + failure);
        }
        System.exit(1);
    }

    /** The labelled form the relay serves once a trade exists. */
    private static void fieldCard() {
        String card = "QoR intraday 2026-10-19 \u00b7 11:14:02 PKT\n"
                + "HCAR\n"
                + "Entry price: 203.0\n"
                + "Exit price: 207.06\n"
                + "Stop Loss: 199.5\n"
                + "One trade already taken today; no further entry is possible.";
        String out = SignalText.compact(card);
        check("the field card keeps its three prices",
                out.equals("Entry Price: 203.0\nExit Price: 207.06\nStop Loss: 199.5"));
    }

    /** The sentence form the daily-locked path writes. */
    private static void sentenceCard() {
        String card = "QoR intraday 2026-10-16 \u00b7 16:29:30 PKT\n"
                + "One trade already taken today: HCAR entered at 203.0, "
                + "target 207.06. position being monitored.";
        String out = SignalText.compact(card);
        check("the sentence card yields the ticker and both prices",
                out.equals("HCAR\nEntry Price: 203.0\nExit Price: 207.06\n"
                        + "Stop Loss: Not reported"));
    }

    /** A market where the rules refused every candidate is one word. */
    private static void noTradeCard() {
        String card = "QoR intraday 2026-10-19 \u00b7 12:30:00 PKT\n"
                + "NO TRADE. Coverage 96%; the momentum rule found no candidate "
                + "that cleared its volume gate.";
        check("a no-trade card is the no-trade word",
                SignalText.NO_TRADE.equals(SignalText.compact(card)));
    }

    /** Nothing to show is stated, never invented as a signal. */
    private static void missingCard() {
        check("null is unavailable", SignalText.UNAVAILABLE.equals(
                SignalText.compact(null)));
        check("blank is unavailable", SignalText.UNAVAILABLE.equals(
                SignalText.compact("   \n  ")));
        check("a card with no numbers is unavailable",
                SignalText.UNAVAILABLE.equals(SignalText.compact(
                        "QoR intraday 2026-10-19 \u00b7 10:00:00 PKT\n"
                                + "the tape was thin this slot")));
    }

    /** The trailing summary starts with "Target" and must not be read as one. */
    private static void summaryTargetIsNotAPrice() {
        String card = "QoR intraday 2026-10-19 \u00b7 10:00:00 PKT\n"
                + "Entry price: 203.0\n"
                + "Target: the momentum rule needs three closes above the gate";
        String out = SignalText.compact(card);
        check("a prose target does not become an exit price",
                out.equals("Entry Price: 203.0\nExit Price: Not reported\n"
                        + "Stop Loss: Not reported"));
        check("the prose itself is not echoed", !out.contains("momentum"));
    }

    /** The owner's order: no header, no date, no clock, no narration. */
    private static void metadataNeverLeaks() {
        String card = "QoR intraday 2026-10-19 \u00b7 11:14:02 PKT\n"
                + "Entry price: 203.0\n"
                + "Exit price: 207.06\n"
                + "Stop Loss: 199.5";
        String out = SignalText.compact(card);
        for (String banned : new String[]{"QoR", "PKT", "2026-10-19", "11:14"}) {
            check("metadata \"" + banned + "\" is not on the tile",
                    !out.contains(banned));
        }
    }

    private static void check(String what, boolean ok) {
        if (!ok) {
            failures.add(what);
        }
    }
}
