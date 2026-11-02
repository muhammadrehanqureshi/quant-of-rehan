package pk.quantofrehan;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * The primary signal data, and nothing else (owner order 2026-10-19).
 *
 * The relay's card is a text block written for a person: a
 * "QoR intraday <date> · <time> PKT" header, then either labelled fields or a
 * sentence, then the rule narration ("one trade already taken today; no
 * further entry is possible; ..."). The tile carries the ticker, the entry
 * time and three labelled prices, or one state word:
 *
 *   QoR intraday 2026-10-16 · 16:29:30 PKT
 *   One trade already taken today: HCAR entered at 203.0, target 207.06.
 *
 *   Entry time: 09:41:07 PKT
 *   Entry price: 203.0
 *   Exit price: 207.06
 *   Stop Loss: 199.5
 *
 * No Android imports: the parsing is exercised on the JVM by
 * tests/test_android_signal_text.py against those exact inputs, so a new card
 * shape fails a test instead of shipping an empty tile.
 */
final class SignalText {

    /** Printed for a price the relay did not report, never a guessed number. */
    static final String NOT_REPORTED = "Not reported";
    static final String NO_TRADE = "NO TRADE";
    static final String UNAVAILABLE = "Signal unavailable";

    /** "HCAR entered at 203.0" / "entered at 203". */
    private static final Pattern ENTERED =
            Pattern.compile("([A-Z0-9]{2,12})\\s+entered\\s+at\\s+(-?[0-9]+(?:\\.[0-9]+)?)",
                    Pattern.CASE_INSENSITIVE);
    /**
     * The first ISO date the card carries (owner order 2026-10-20).
     *
     * A card opens with the session it was written for, so the first
     * yyyy-MM-dd in the text is that session. Reading a date is not printing
     * one: the tile still shows the ticker, the entry time and three prices,
     * and this parser
     * names no header wording of its own, so the copy can change without
     * leaving a second spelling of it in the code.
     */
    private static final Pattern CARD_DATE =
            Pattern.compile("\\b(\\d{4}-\\d{2}-\\d{2})\\b");
    /** The stamp of the trade itself, never the card header's slot. */
    private static final Pattern ENTRY_TIME =
            Pattern.compile("\\bentry\\s*time\\s*:\\s*"
                    + "([0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?)",
                    Pattern.CASE_INSENSITIVE);
    private static final Pattern TARGET =
            Pattern.compile("\\btarget\\s+(-?[0-9]+(?:\\.[0-9]+)?)",
                    Pattern.CASE_INSENSITIVE);
    private static final Pattern STOP =
            Pattern.compile("\\b(?:stop\\s*loss|stop|sl)\\b\\s*(?:at\\s+)?"
                    + "(-?[0-9]+(?:\\.[0-9]+)?)", Pattern.CASE_INSENSITIVE);

    private SignalText() {
    }

    /**
     * The session the card was written for, "yyyy-MM-dd", or "" when the text
     * carries no header. A tile that cannot name today must never pass another
     * day's call off as today's (owner order 2026-10-20).
     */
    static String cardDate(String raw) {
        if (raw == null) {
            return "";
        }
        Matcher m = CARD_DATE.matcher(raw);
        return m.find() ? m.group(1) : "";
    }

    /** The ticker, entry time and three prices, else one state word. */
    static String compact(String raw) {
        if (raw == null) {
            return UNAVAILABLE;
        }
        String text = raw.trim();
        if (text.isEmpty()) {
            return UNAVAILABLE;
        }

        String symbol = null;
        String entryTime = null;
        String entry = null;
        String exit = null;
        String stop = null;
        for (String line : text.split("\\r?\\n")) {
            String value;
            if ((value = afterLabel(line, "Symbol:")) != null) {
                symbol = symbolName(value);
            } else if ((value = afterLabel(line, "Entry price:")) != null) {
                entry = value;
            } else if ((value = afterLabel(line, "Exit price:")) != null) {
                exit = value;
            } else if ((value = afterLabel(line, "Exit reference:")) != null) {
                exit = value;
            } else if ((value = afterLabel(line, "Exit:")) != null) {
                exit = value;
            } else if ((value = afterLabel(line, "Stop Loss:")) != null) {
                stop = value;
            } else if ((value = afterLabel(line, "SL:")) != null) {
                stop = value;
            } else if ((value = afterLabel(line, "Target:")) != null) {
                // The trailing summary also starts with Target but carries no
                // price, so only a numeric value is kept.
                String numeric = leadingPrice(value);
                if (numeric != null) {
                    exit = numeric;
                }
            }
        }
        Matcher when = ENTRY_TIME.matcher(text);
        if (when.find()) {
            entryTime = when.group(1);
        }
        if (entry == null && exit == null && stop == null) {
            // The sentence form the runner writes for a taken trade.
            Matcher entered = ENTERED.matcher(text);
            if (entered.find()) {
                symbol = entered.group(1).toUpperCase(java.util.Locale.US);
                entry = entered.group(2);
                Matcher target = TARGET.matcher(text);
                if (target.find()) {
                    exit = target.group(1);
                }
                Matcher halt = STOP.matcher(text);
                if (halt.find()) {
                    stop = halt.group(1);
                }
            }
        }
        if (entry == null && exit == null && stop == null) {
            return text.toUpperCase(java.util.Locale.US).contains("NO TRADE")
                    ? NO_TRADE : UNAVAILABLE;
        }
        StringBuilder out = new StringBuilder();
        if (symbol != null) {
            out.append(symbol).append('\n');
        }
        out.append("Entry Time: ").append(orNotReported(entryTime))
                .append('\n').append("Entry Price: ").append(orNotReported(entry))
                .append('\n').append("Exit Price: ").append(orNotReported(exit))
                .append('\n').append("Stop Loss: ").append(orNotReported(stop));
        return out.toString();
    }

    private static String afterLabel(String line, String label) {
        if (line == null || !line.regionMatches(true, 0, label, 0, label.length())) {
            return null;
        }
        String value = line.substring(label.length()).trim();
        return known(value);
    }

    private static String known(String value) {
        if (value == null) return null;
        String trimmed = value.trim();
        return trimmed.isEmpty() || "null".equalsIgnoreCase(trimmed)
                || "undefined".equalsIgnoreCase(trimmed) ? null : trimmed;
    }

    private static String leadingPrice(String value) {
        String known = known(value);
        if (known == null) return null;
        String first = known.split("\\s+", 2)[0];
        try {
            double price = Double.parseDouble(first);
            return price > 0.0 && !Double.isNaN(price) && !Double.isInfinite(price)
                    ? first : null;
        } catch (NumberFormatException invalid) {
            return null;
        }
    }

    /** A labelled ticker is a ticker, never the whole descriptive line. */
    private static String symbolName(String value) {
        String known = known(value);
        if (known == null) return null;
        String first = known.split("\\s+", 2)[0].toUpperCase(java.util.Locale.US);
        return first.matches("[A-Z0-9]{2,12}") ? first : null;
    }

    private static String orNotReported(String value) {
        return value == null ? NOT_REPORTED : value;
    }
}
