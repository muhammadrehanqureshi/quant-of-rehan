package pk.quantofrehan;

import java.util.ArrayList;
import java.util.List;

/**
 * Runs SignalText on the JVM against the cards the runner actually writes.
 *
 * The Android source tests can only read Java as text, which cannot tell a
 * parser that returns the trade's own entry time from one that returns the
 * header. This probe compiles the real class and checks both card shapes, the
 * no-trade state, and the absences the owner ordered: no header date, no
 * header slot and no rule narration in the tile.
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
        mtfCard();
        noTradeCard();
        missingCard();
        summaryTargetIsNotAPrice();
        rememberedEntryTime();
        metadataNeverLeaks();

        if (failures.isEmpty()) {
            System.out.println("PASS SignalText: 8 cases");
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
                + "Symbol: HCAR\n"
                + "Entry price: 203.0\n"
                + "Exit price: 207.06\n"
                + "Stop Loss: 199.5\n"
                + "Entry time: 09:41:07 PKT\n"
                + "One trade already taken today; no further entry is possible.";
        String out = SignalText.compact(card);
        check("the field card keeps its ticker, entry time and three prices",
                out.equals("HCAR\nEntry Time: 09:41:07\nEntry Price: 203.0\n"
                        + "Target Price: 207.06\nStop Loss: 199.5"));
    }

    /** The sentence form the daily-locked path writes. */
    private static void sentenceCard() {
        String card = "QoR intraday 2026-10-16 \u00b7 16:29:30 PKT\n"
                + "One trade already taken today: HCAR entered at 203.0, "
                + "target 207.06, stop loss 199.5. Entry time: 09:41:07 PKT. "
                + "position being monitored.";
        String out = SignalText.compact(card);
        check("the sentence card yields the ticker, time and three prices",
                out.equals("HCAR\nEntry Time: 09:41:07\nEntry Price: 203.0\n"
                        + "Target Price: 207.06\nStop Loss: 199.5"));
    }

    /** The cloud's four frame line survives the compact tile unchanged. */
    private static void mtfCard() {
        String card = "QoR intraday 2026-11-03 | 14:30:00 PKT\n"
                + "Symbol: HCAR\n"
                + "Entry price: 203.0\n"
                + "Exit price: 207.06\n"
                + "Stop Loss: 199.5\n"
                + "Entry time: 09:41:07 PKT\n"
                + "MTF 5m +1 above VWAP | 15m +1 above VWAP | "
                + "1h +1 above VWAP | 1D +1 above VWAP";
        String out = SignalText.compact(card);
        check("the cloud MTF line stays on the tile",
                out.endsWith("\nMTF 5m +1 above VWAP | 15m +1 above VWAP | "
                        + "1h +1 above VWAP | 1D +1 above VWAP"));
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
                out.equals("Entry Time: Not reported\nEntry Price: 203.0\n"
                        + "Target Price: Not reported\nStop Loss: Not reported"));
        check("the prose itself is not echoed", !out.contains("momentum"));
    }

    /** A later daily-lock card inherits the stamp its session already showed. */
    private static void rememberedEntryTime() {
        String card = "QoR intraday 2026-11-02 | 12:10:00 PKT\n"
                + "Symbol: HCAR\n"
                + "Entry price: 203.0\n"
                + "Target: 207.06\n"
                + "Stop Loss: 199.5";
        String out = SignalText.compact(card, "09:41:07");
        check("a remembered entry time fills a later card",
                out.contains("Entry Time: 09:41:07"));
        String explicit = card.replace("Entry price: 203.0\n",
                "Entry price: 203.0\nEntry time: 10:00:00 PKT\n");
        check("an explicit entry time wins over the remembered one",
                SignalText.compact(explicit, "09:41:07")
                        .contains("Entry Time: 10:00:00"));
    }

    /** The owner's order: no header, no date, no header clock, no narration. */
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
        check("the header time is never invented as the entry time",
                out.contains("Entry Time: Not reported"));
    }

    private static void check(String what, boolean ok) {
        if (!ok) {
            failures.add(what);
        }
    }
}
