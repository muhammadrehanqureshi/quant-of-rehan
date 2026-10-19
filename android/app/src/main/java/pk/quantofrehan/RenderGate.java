package pk.quantofrehan;

/**
 * Decides whether a relay answer changes what the console draws.
 *
 * The console polls once a second while the market is live (owner order
 * 2026-10-16), but the relay's own clock has minute resolution and its card
 * changes only when the cloud capture publishes. Most answers are therefore
 * byte-identical to the one before them, and repainting them is not free:
 * every setText invalidates the TextView, re-measures it and lays the tile out
 * again, and the status badge used to build a fresh GradientDrawable per
 * answer. On a phone that is a whole-tile relayout every second to show the
 * same pixels.
 *
 * So the answer is compared with the last one painted, field by field, and the
 * paint is skipped when nothing moved. Two rules keep this honest:
 *
 *   - it compares the ANSWER, never a view. No value is ever taken from a
 *     TextView, so a skipped paint cannot leave the model and the screen
 *     disagreeing in the other direction;
 *   - the first answer after a reset is always a change, because a fresh
 *     console has painted nothing yet.
 *
 * The class has no Android imports on purpose: it is plain Java, so the
 * decision is exercised on the JVM by tests/test_android_render_gate.py
 * instead of only being read as source.
 */
final class RenderGate {

    /** False until one answer has been painted: the first is always news. */
    private boolean primed;

    private boolean online;
    private String detail = "";
    private String signals = "";
    private int market;

    /**
     * True when this answer differs from the last one painted, and records it.
     *
     * A null detail or signals is read as the empty string, which is how the
     * console renders both: the caller passes the relay's text straight
     * through and a missing field must compare equal to an empty one.
     */
    boolean changed(boolean online, String detail, String signals, int market) {
        String nextDetail = detail == null ? "" : detail;
        String nextSignals = signals == null ? "" : signals;
        boolean differs = !primed
                || online != this.online
                || market != this.market
                || !nextDetail.equals(this.detail)
                || !nextSignals.equals(this.signals);
        if (differs) {
            primed = true;
            this.online = online;
            this.detail = nextDetail;
            this.signals = nextSignals;
            this.market = market;
        }
        return differs;
    }

    /**
     * Forget what was painted, so the next answer repaints.
     *
     * Called when the console is resumed: onPause stops the status breath, and
     * a resumed console whose answer happens to equal the one it showed before
     * it was hidden still has to paint, because that paint is what restarts
     * the breath on a live market.
     */
    void reset() {
        primed = false;
    }
}
