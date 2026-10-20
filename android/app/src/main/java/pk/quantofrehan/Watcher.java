package pk.quantofrehan;

import android.app.AlarmManager;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.math.BigDecimal;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Talks to the relay on the Cloudflare edge, posts notifications, and keeps
 * the watchdog armed. All system questions are answered by the relay; this
 * app never talks to Telegram, the broker or the exchange (SO-1, SO-9).
 */
public final class Watcher {

    static final String DEFAULT_RELAY =
            "https://quant-of-rehan-relay.mrmrehanqureshi.workers.dev";
    private static final String CHANNEL_STATUS = "system_status";
    private static final String CHANNEL_SIGNALS = "signals";

    // Owner order 2026-10-19 moved the strategy scanner to a one second
    // cadence, so the foreground display poll and the scan now share one
    // number. This class still only reads the relay: it never scans.
    static final long REFRESH_MS = 30 * 1000;
    static final long FAST_POLL_MS = 1000;
    // A fast health/signals/card refresh is still a display read, not a scan.
    static final long DISPLAY_REFRESH_MS = FAST_POLL_MS;

    /**
     * One relay answer, before the market card is asked for.
     *
     * The two fetch rounds share this: the full round adds the card, the live
     * round stops here. Keeping one reader means the ONLINE rule, the phase
     * fallback and the signal note cannot drift between the two cadences.
     */
    private static final class Head {
        boolean reachable;
        boolean marketOpen;
        String detail = "";
        String signals = "";
        /** The relay's own phase, from /health alone (no card involved). */
        Market phase = new Market();

        boolean online() {
            return reachable && marketOpen;
        }
    }

    // The background re-arm stays at five minutes, and that is a platform
    // fact rather than a preference: an AlarmManager wake is not a poll.
    // setExactAndAllowWhileIdle is capped to roughly one wake per nine minutes
    // inside Doze and is stopped outright by some OEM battery managers, so a
    // 30 second alarm would advertise a cadence Android will not honour. This
    // arm is only the watchdog that wakes a CLOSED app; a signal that lands
    // between two arms is delivered by the relay's own notification.
    static final long WATCHDOG_MS = 1000;

    /**
     * Hard cap on an accepted relay body.
     *
     * The card is a few kilobytes of JSON, so anything past this is a spike, a
     * truncated stream or a wrong endpoint. Reading it unbounded would let one
     * bad response exhaust the heap and kill the app, which is exactly the
     * "broker feed data spike" failure this cap exists to prevent.
     */
    private static final int MAX_BODY_CHARS = 512 * 1024;

    private static final ExecutorService POOL = Executors.newSingleThreadExecutor();
    /**
     * The symbols the relay's newest snapshot carries, sorted. The search
     * filters this list, so a keystroke costs no request (owner order
     * 2026-10-20).
     */
    private static volatile java.util.List<String> SYMBOLS =
            java.util.Collections.emptyList();

    private Watcher() {
    }

    /** The relay answered with more data than this app accepts. */
    static final class PayloadTooLarge extends IOException {
        PayloadTooLarge() {
            super("relay body exceeded " + MAX_BODY_CHARS + " characters");
        }
    }

    /**
     * One of the day's most traded KMIALL stocks.
     *
     * Strict typing for the financial fields: every value is a boxed Number
     * whose null means "the relay did not report this". A primitive with a
     * NaN or -1 sentinel looks like a value to the compiler, so an unknown
     * price silently flows through arithmetic and prints as a number. Boxed
     * nulls make the unknown case impossible to ignore at the read site.
     */
    static final class Leader {
        String symbol = "";
        /** null: the relay reported no price for this symbol. */
        Double price;
        /** null: the relay reported no day's movement. */
        Double changePct;
        /** null: the relay reported no volume. */
        Long volume;
        /** null: no buy/sell split arrived. */
        Long buy;
        /** null: no buy/sell split arrived. */
        Long sell;
        /**
         * How the relay produced the split: "measured_tape" when the numbers
         * came from the session's own trade tape, "range_position" when they
         * are a labelled estimate from the day's range. Empty when no split
         * arrived at all.
         */
        String splitMethod = "";

        /**
         * True when a labelled buy/sell split arrived for this stock.
         *
         * Labeled, not proven: the relay says whether the numbers were
         * measured from the session tape or estimated from the day's range
         * (SO-3). The app renders the split either way and never presents the
         * estimate as order flow of its own accord.
         */
        boolean hasSplit() {
            return buy != null && sell != null;
        }

        /**
         * True when the split is the venue-range estimate rather than the
         * session tape, so the row marks it as one (SO-3).
         *
         * Owner order 2026-10-12 removed the card's footnote, which is where
         * this distinction used to be spelled out, so the number itself now
         * carries the mark: an estimate prints as B≈ / S≈. An unknown method
         * counts as estimated, because the safe reading of an unlabelled
         * number is the weaker claim.
         *
         * Owner order 2026-10-15: the numbers the session tape counted are
         * the feed's own, exact values, so they print with a plain "=",
         * whether the tape covered the whole day (``measured_tape``) or the
         * part of it it saw (``tape_counts``). The window those counts cover
         * travels in the row's own label, not in a weaker mark, because the
         * digits are not an estimate of anything.
         */
        boolean estimatedSplit() {
            if (!hasSplit()) return false;
            return !("measured_tape".equals(splitMethod)
                    || "tape_counts".equals(splitMethod));
        }

        /** True when the exchange's own total volume arrived. */
        boolean hasVolume() {
            return volume != null;
        }
    }

    /** What the app knows about the exchange at this instant. */
    static final class Market {
        boolean answered;
        boolean open;
        /** The relay's Karachi date, "yyyy-MM-dd", or empty when unreported.
         *  The console compares a signal card's own session against this, so
         *  "is this call today's?" is answered by the edge's clock (SO-8). */
        String date = "";
        /** OPEN, BREAK, CLOSED, PRE_OPEN or POST_CLOSE, or null when the
         *  relay did not report a phase. The app never guesses one. */
        String phase;
        /** OPERATIONAL, BREAK or CLOSED, or empty when the relay reported
         *  none. This is the relay's own three valued condition (2026-10-11),
         *  and it is the field the session sentences are read from. */
        String condition = "";
        /** The relay's exact sentence for that condition, or empty. */
        String conditionText = "";
        boolean tradingDay = true;
        Double indexValue;
        Double indexChange;
        Double indexPct;
        String indexAsOf = "";
        String indexSource = "";
        String feedStatus = "UNKNOWN";
        String feedStatusRaw = "";
        String feedStatusAsOf = "";
        boolean feedStatusFresh;
        boolean feedHalted;
        String transitionState = "";
        String transitionEvidence = "";
        boolean transitionDelivered;
        final List<Leader> leaders = new ArrayList<>();
        String basis = "";
        String splitBasis = "";
        String note = "";
        int cacheAgeSeconds = -1;

        /** True only when the index and both of its movements are known. */
        boolean hasIndex() {
            return indexValue != null && indexChange != null && indexPct != null;
        }

        /** True only when the relay actually reported a session phase. */
        boolean phaseKnown() {
            return phase != null && !phase.isEmpty();
        }

        boolean isLive() {
            return open && !"BREAK".equals(phase);
        }
    }

    interface Callback {
        void done(boolean online, boolean reachable, String detail,
                  String signals, Market market);
    }

    static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences("qor", Context.MODE_PRIVATE);
    }

    static String relayUrl(Context c) {
        String saved = prefs(c).getString("relay_url", "");
        return saved.isEmpty() ? DEFAULT_RELAY : saved;
    }

    /**
     * A JSON number, or null when the relay sent null, omitted the key, or
     * sent a value that is not a finite number.
     *
     * This is the numeric hygiene gate for every financial field on the card:
     * a NaN or an infinity can never reach the UI, because it becomes an
     * explicit "unknown" instead.
     */
    private static Double numberOrNull(JSONObject row, String key) {
        if (row == null || row.isNull(key)) {
            return null;
        }
        double value = row.optDouble(key, Double.NaN);
        return (Double.isNaN(value) || Double.isInfinite(value)) ? null : value;
    }

    /**
     * A non-negative, exact whole share count, or null when absent or invalid.
     * Never rounds a broker value: fractional, non-finite and overflowing
     * counts are rejected rather than displayed as a different quantity.
     */
    private static Long integerOrNull(JSONObject row, String key) {
        if (row == null || row.isNull(key)) {
            return null;
        }
        Object raw = row.opt(key);
        if (!(raw instanceof Number)) {
            return null;
        }
        try {
            long value = new BigDecimal(raw.toString()).longValueExact();
            return value < 0 ? null : value;
        } catch (NumberFormatException | ArithmeticException invalidCount) {
            return null;
        }
    }

    /** Read at most MAX_BODY_CHARS characters, so a spike cannot exhaust the heap. */
    private static String readBounded(InputStream stream) throws IOException {
        StringBuilder sb = new StringBuilder(4096);
        char[] buffer = new char[8192];
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            int read;
            while ((read = reader.read(buffer)) != -1) {
                if (sb.length() + read > MAX_BODY_CHARS) {
                    throw new PayloadTooLarge();
                }
                sb.append(buffer, 0, read);
            }
        }
        return sb.toString();
    }

    /**
     * One raw GET; returns the parsed body or throws.
     *
     * A truncated or malformed body makes the JSON constructor throw, and the
     * callers below turn that into a footnote. A bad payload empties the card,
     * it never crashes the app.
     */
    private static JSONObject get(String url, String admin) throws Exception {
        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        conn.setConnectTimeout(8000);
        conn.setReadTimeout(12000);
        if (admin != null && !admin.isEmpty()) {
            conn.setRequestProperty("x-admin-token", admin);
        }
        int code = conn.getResponseCode();
        InputStream stream = code >= 400 ? conn.getErrorStream() : conn.getInputStream();
        if (stream == null) {
            // getErrorStream() is null for some failures, so say so rather than
            // dereferencing it and throwing a NullPointerException.
            throw new IOException("relay returned HTTP " + code + " with no body");
        }
        return new JSONObject(readBounded(stream));
    }

    /** Health with one retry, so a single dropped packet does not alarm. */
    private static JSONObject healthWithRetry(String base) throws Exception {
        Exception last = null;
        for (int attempt = 0; attempt < 2; attempt++) {
            try {
                return get(base + "/health", null);
            } catch (Exception e) {
                last = e;
                try {
                    Thread.sleep(1500);
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    throw ie;
                }
            }
        }
        throw last;
    }

    /**
     * The relay's market card: fresh broker-feed KSE100, REG market status
     * and KMIALL volume leaders, with a labelled PSX portal fallback. A card
     * failure never changes the session status badge.
     */
    static Market fetchMarket(Context c, String base) {
        Market market = new Market();
        try {
            JSONObject body = get(base + "/market", null);
            market.answered = body.optBoolean("ok", false);
            market.open = body.optBoolean("market_open", false);
            market.date = body.optString("date", "");
            JSONObject transition = body.optJSONObject("market_transition");
            if (transition != null) {
                market.transitionState = transition.optString("state", "");
                market.transitionEvidence = transition.optString("evidence", "");
                market.transitionDelivered = transition.optBoolean("delivered", false);
            }
            market.cacheAgeSeconds = body.optInt("cache_age_seconds", -1);
            market.basis = body.optString("top_volume_basis", "");
            market.splitBasis = body.optString("volume_split_basis", "");
            readPhase(body.optJSONObject("market_state"), market);
            JSONObject feedStatus = body.optJSONObject("market_feed");
            if (feedStatus != null) {
                market.feedStatus = feedStatus.optString("status", "UNKNOWN");
                market.feedHalted = "HALTED".equals(market.feedStatus)
                        && feedStatus.optBoolean("fresh", false);
                market.feedStatusRaw = feedStatus.optString("raw_status", "");
                market.feedStatusAsOf = feedStatus.optString("as_of", "");
                market.feedStatusFresh = feedStatus.optBoolean("fresh", false);
            }

            JSONObject index = body.optJSONObject("index");
            if (index != null) {
                market.indexValue = numberOrNull(index, "value");
                market.indexChange = numberOrNull(index, "change");
                market.indexPct = numberOrNull(index, "change_pct");
                market.indexAsOf = index.optString("as_of", "");
                market.indexSource = index.optString("source", "");
            }

            JSONArray tops = body.optJSONArray("top_volume");
            if (tops != null) {
                for (int i = 0; i < tops.length() && i < 3; i++) {
                    JSONObject row = tops.optJSONObject(i);
                    if (row == null) continue;
                    Leader leader = new Leader();
                    leader.symbol = row.optString("symbol", "");
                    leader.volume = integerOrNull(row, "volume");
                    leader.price = numberOrNull(row, "price");
                    leader.changePct = numberOrNull(row, "change_pct");
                    leader.buy = integerOrNull(row, "buy_volume");
                    leader.sell = integerOrNull(row, "sell_volume");
                    leader.splitMethod = row.optString("split_method", "");
                    market.leaders.add(leader);
                }
            }
            JSONArray notes = body.optJSONArray("notes");
            if (notes != null && notes.length() > 0) {
                market.note = notes.optString(0, "");
            }
            if (body.optBoolean("stale", false)) {
                market.note = "relay last refreshed earlier: " + market.note;
            }
        } catch (PayloadTooLarge spike) {
            // Distinguished from a generic failure on purpose: a payload spike
            // is an operational fact the owner can act on, not a parse error.
            market.note = c.getString(R.string.market_payload_too_large);
        } catch (Exception e) {
            market.note = c.getString(R.string.market_card_failed,
                    e.getClass().getSimpleName());
        }
        return market;
    }

    /**
     * Read the relay's market_state block into the card state.
     *
     * The relay is the authority on whether the exchange is open: the app
     * never derives a session from its own clock, which is how a phone in
     * another timezone (or a PC whose clock has drifted) would otherwise
     * disagree with the exchange about the Friday midday break.
     *
     * A missing or empty phase leaves `phase` null, which the copy then
     * reports as unreported rather than guessing a session (SO-3, SO-8).
     */
    private static void readPhase(JSONObject state, Market market) {
        if (state == null) return;
        String phase = state.optString("phase", "");
        if (!phase.isEmpty()) {
            market.phase = phase;
        }
        String condition = state.optString("condition", "");
        if (!condition.isEmpty()) {
            market.condition = condition;
        }
        market.conditionText = state.optString("condition_text", "");
        market.tradingDay = state.optBoolean("trading_day", market.tradingDay);
        if (state.has("market_open")) {
            market.open = state.optBoolean("market_open", market.open);
        }
    }

    /**
     * The owner-facing sentence for the market's condition, or "" while the
     * exchange is trading. Never guesses a session.
     *
     * A fresh broker-wide halt has priority over the session schedule. Otherwise
     * the relay reports its three valued condition and its sentence, and both
     * are the owner's exact words, so they win whenever they arrive. A relay
     * too old to carry them falls back to the phase, and
     * CLOSED, PRE_OPEN and POST_CLOSE all read as one closed sentence, which
     * is true in each. An unreported phase still says so rather than claiming
     * a session the relay never confirmed.
     */
    static String phaseLine(Context c, Market market) {
        if (market != null && market.feedHalted && market.feedStatusFresh) {
            return c.getString(R.string.market_halted_now);
        }
        if (market == null || !market.phaseKnown()) {
            return c.getString(R.string.market_status_unreported);
        }
        if ("OPERATIONAL".equals(market.condition)) {
            return "";
        }
        if ("BREAK".equals(market.condition)) {
            return market.conditionText.isEmpty()
                    ? c.getString(R.string.market_on_break) : market.conditionText;
        }
        if ("CLOSED".equals(market.condition)) {
            return market.conditionText.isEmpty()
                    ? c.getString(R.string.market_closed_now) : market.conditionText;
        }
        String phase = market.phase;
        if ("OPEN".equals(phase) || "WARMUP".equals(phase)) {
            return "";
        }
        if ("BREAK".equals(phase)) {
            return c.getString(R.string.market_on_break);
        }
        // CLOSED (a weekend or a PSX holiday), PRE_OPEN and POST_CLOSE all read
        // as one closed sentence: that is the owner's wording, and it is true
        // in each of them.
        return c.getString(R.string.market_closed_now);
    }

    /**
     * One fetch round. ONLINE means a live session AND a relay that answers.
     * The owner's rule (2026-10-09): when the market is closed the app must
     * say OFFLINE with a red cross, never ONLINE.
     */
    /**
     * One answer from /health plus one from /signals (owner order 2026-10-16).
     *
     * This is the pair a live round reads: the relay's OWN state, which is
     * what changes between two scans. /health also carries the session phase,
     * so a fast round still keeps the pill, the sentence and the market state
     * true without touching the exchange-backed card.
     */
    private static Head fetchHead(Context c, String base) throws Exception {
        Head head = new Head();
        JSONObject health = healthWithRetry(base);
        head.reachable = health.optBoolean("ok", false);
        head.marketOpen = health.optBoolean("market_open", false);
        String karachi = health.optString("karachi_now", "");

        // The relay's own phase decides the sentence, so a break reads as a
        // break and a weekend reads as a weekend (v1.6.0).
        head.phase.open = head.marketOpen;
        readPhase(health.optJSONObject("market_state"), head.phase);

        // owner order 2026-10-07: the app shows only the Karachi clock; the
        // next-event line is gone
        if (!head.reachable) {
            head.detail = "The relay answered but reported a fault.";
        } else {
            StringBuilder d = new StringBuilder("Karachi: ").append(karachi);
            String line = phaseLine(c, head.phase);
            if (!line.isEmpty()) {
                d.append('\n').append(line);
            }
            // Owner order 2026-10-13: the "Trading resumes" sentence is
            // retired, so the tile carries the condition alone.
            head.detail = d.toString();
        }

        // Owner order 2026-10-19: the phone carries no admin token, so the
        // relay serves the latest signal as a public read (its write route
        // stays admin gated). A failure here is reported in the tile and never
        // invented as a signal.
        String signalNote = "";
        try {
            JSONObject sig = get(base + "/signals", null);
            if (sig.optBoolean("ok")) {
                head.signals = sig.optString("signals", "");
            } else {
                signalNote = "Signals are unavailable from the relay.";
            }
        } catch (Exception se) {
            signalNote = "Signals could not load just now.";
        }
        if (!signalNote.isEmpty() && head.signals.trim().isEmpty()) {
            head.signals = signalNote;
        }
        return head;
    }

    /**
     * The foreground refresh: current session status, signals and the relay's
     * latest broker snapshot. This is a display read, not a strategy scan; the
     * upstream feed publication cadence is reported by its source timestamps.
     * This pulls the /market endpoint whose session cache can otherwise be
     * five minutes old; the frequent poll does not create upstream feed data.
     */
    static void fetchLive(final Context c, final Callback cb) {
        POOL.execute(() -> {
            String base = relayUrl(c);
            try {
                Head head = fetchHead(c, base);
                Market market = fetchMarket(c, base);
                applyLiveQuotes(market, base);
                cb.done(head.online(), head.reachable, head.detail,
                        head.signals, market);
            } catch (Exception e) {
                String why = e.getClass().getSimpleName();
                String hint = why.contains("UnknownHost") || why.contains("Connect")
                        ? "No route to the relay from this phone. Check internet or VPN."
                        : "The relay did not answer in time. Will retry.";
                cb.done(false, false, hint + " (" + why + ")", "", null);
            }
        });
    }

    /** The full round: the head above, plus the exchange-backed market card. */
    static void fetchStatus(final Context c, final Callback cb) {
        POOL.execute(() -> {
            String base = relayUrl(c);
            try {
                Head head = fetchHead(c, base);
                Market market = fetchMarket(c, base);
                applyLiveQuotes(market, base);
                if (!market.phaseKnown()) {
                    // the card failed to load: keep the phase the relay already
                    // told us, so the pill and the footnote never disagree
                    market.phase = head.phase.phase;
                    market.tradingDay = head.phase.tradingDay;
                    market.open = head.phase.open;
                }
                cb.done(head.online(), head.reachable, head.detail,
                        head.signals, market);
            } catch (Exception e) {
                String why = e.getClass().getSimpleName();
                String hint = why.contains("UnknownHost") || why.contains("Connect")
                        ? "No route to the relay from this phone. Check internet or VPN."
                        : "The relay did not answer in time. Will retry.";
                Market market = new Market();
                market.note = c.getString(R.string.market_relay_unreachable);
                cb.done(false, false, hint + " (" + why + ")", "", market);
            }
        });
    }

    /**
     * Overlay the live broker snapshot on the market card (owner order
     * 2026-10-19: the numbers must move as they do in the broker terminal).
     *
     * Two layers feed this card and they move at different speeds. /market is
     * the slow one: the relay rebuilds it from the cloud capture and stores it
     * in KV, so its KSE100 line can sit unchanged for minutes. /quotes is the
     * fast one: the Durable Object holds the newest frame set the capture
     * pushed, one row per symbol plus the index, each stamped by the broker.
     *
     * So a FRESH index from the snapshot wins, and each leader's price and
     * movement come from its own live quote. A stale row never overwrites a
     * card value: ageing a number forward is the one thing this app must not
     * do (SO-3). If the snapshot is missing or unparseable the card stands on
     * its own, unchanged.
     */
    private static void applyLiveQuotes(Market market, String base) {
        JSONObject snapshot;
        try {
            snapshot = get(base + "/quotes", null);
        } catch (Exception unreachable) {
            return;
        }
        if (!snapshot.optBoolean("ok", false)) return;

        JSONObject index = snapshot.optJSONObject("index");
        if (index != null && index.optBoolean("fresh", false)) {
            Double value = numberOrNull(index, "value");
            Double change = numberOrNull(index, "change");
            Double pct = numberOrNull(index, "change_pct");
            if (value != null && change != null && pct != null && value > 0) {
                market.indexValue = value;
                market.indexChange = change;
                market.indexPct = pct;
                market.indexAsOf = index.optString("as_of", market.indexAsOf);
                market.indexSource = "broker feed";
            }
        }

        JSONArray quotes = snapshot.optJSONArray("quotes");
        if (quotes == null) return;
        Map<String, JSONObject> live = new HashMap<>();
        for (int i = 0; i < quotes.length(); i++) {
            JSONObject quote = quotes.optJSONObject(i);
            if (quote != null) {
                live.put(quote.optString("symbol", ""), quote);
            }
        }
        // The search's universe is the relay's own snapshot, so the list moves
        // with the market instead of being baked into the APK.
        java.util.List<String> names = new java.util.ArrayList<>(live.keySet());
        names.remove("");
        java.util.Collections.sort(names);
        SYMBOLS = java.util.Collections.unmodifiableList(names);
        if (market.leaders.isEmpty()) return;
        for (Leader leader : market.leaders) {
            JSONObject quote = live.get(leader.symbol);
            if (quote == null || !quote.optBoolean("fresh", false)) continue;
            Double price = numberOrNull(quote, "price");
            if (price == null || price <= 0) continue;
            leader.price = price;
            Double pct = numberOrNull(quote, "change_pct");
            if (pct != null) {
                leader.changePct = pct;
            }
        }
    }

    /** Watchdog beat: fetch, compare, notify on change or on signals. */
    static void beat(final Context c) {
        fetchStatus(c, (online, reachable, detail, signals, market) -> {
            SharedPreferences p = prefs(c);

            // The relay's reachability is its own event; a closed market is
            // not an outage and must never be reported as one.
            boolean wasReachable = p.getBoolean("last_reachable", true);
            if (reachable != wasReachable) {
                notifyStatus(c, reachable);
                p.edit().putBoolean("last_reachable", reachable).apply();
            } else if (reachable) {
                // quiet heartbeat: refresh the "still working" timestamp only
                p.edit().putLong("last_seen_ms", System.currentTimeMillis()).apply();
            }
            p.edit().putBoolean("last_online", online).apply();
            p.edit().putLong("market_fetched_ms", System.currentTimeMillis()).apply();

            // owner order 2026-10-08: the app must send EVERY notification,
            // including market open and close, not only relay up/down.
            int mkt = market.open ? 1 : 0;
            int prev = p.getInt("last_market_open", -1);
            if (prev == -1) {
                // first reading after install: record silently
                p.edit().putInt("last_market_open", mkt).apply();
            } else if (mkt != prev) {
                notifyMarket(c, mkt == 1, detail);
                p.edit().putInt("last_market_open", mkt).apply();
            }

            if (signals.trim().isEmpty()
                    || signals.trim().startsWith("The relay ")
                    || signals.trim().startsWith("Signals ")) {
                return; // informational note, never a signal alert
            }
            // owner order 2026-10-08: the daily "No signal today" notice is
            // not a signal and must not ring the phone.
            if (signals.contains("No signal today")) {
                return;
            }
            String last = p.getString("last_signal", "");
            if (!signals.trim().equals(last)) {
                notifySignal(c, signals.trim());
                p.edit().putString("last_signal", signals.trim()).apply();
            }
        });
    }

    /** The relay's snapshot symbols, sorted. Empty until the first answer. */
    static java.util.List<String> symbols() {
        return SYMBOLS;
    }

    interface StockCallback {
        void done(boolean ok, String line);
    }

    /**
     * One symbol's B, S and T, straight from the relay's own split law.
     *
     * The split is computed by the relay (cloud/worker.js), not here: a second
     * implementation of the same law in Java is exactly how two answers to one
     * question start disagreeing. The relay labels the method it used, and an
     * estimated split says so on the line.
     */
    static void fetchStock(final Context c, final String symbol,
                           final StockCallback cb) {
        POOL.execute(() -> {
            String base = relayUrl(c);
            try {
                JSONObject answer = get(base + "/stock?symbol="
                        + java.net.URLEncoder.encode(symbol, "UTF-8"), null);
                JSONObject row = answer.optJSONObject("stock");
                if (!answer.optBoolean("ok", false) || row == null) {
                    cb.done(false, "");
                    return;
                }
                StringBuilder sb = new StringBuilder(row.optString("symbol", symbol));
                Double buy = numberOrNull(row, "buy_volume");
                Double sell = numberOrNull(row, "sell_volume");
                Double total = numberOrNull(row, "volume");
                if (buy != null && sell != null) {
                    sb.append(String.format(java.util.Locale.US,
                            "  (B=%,.0f  S=%,.0f", buy, sell));
                    if (total != null) {
                        sb.append(String.format(java.util.Locale.US, "  T=%,.0f", total));
                    }
                    sb.append(')');
                    if ("range_position".equals(row.optString("split_method", ""))) {
                        sb.append("  EST");
                    }
                } else if (total != null) {
                    sb.append(String.format(java.util.Locale.US, "  (T=%,.0f)", total));
                }
                Double price = numberOrNull(row, "price");
                if (price != null) {
                    sb.append(String.format(java.util.Locale.US, "\nPKR %,.2f", price));
                }
                Double pct = numberOrNull(row, "change_pct");
                if (pct != null) {
                    sb.append(String.format(java.util.Locale.US, "  %s %.2f%%",
                            pct >= 0 ? "\u25B2" : "\u25BC", Math.abs(pct)));
                }
                cb.done(true, sb.toString());
            } catch (Exception e) {
                cb.done(false, "");
            }
        });
    }

    static void armAlarms(Context c) {
        AlarmManager am = (AlarmManager) c.getSystemService(Context.ALARM_SERVICE);
        Intent i = new Intent(c, PollReceiver.class);
        PendingIntent pi = PendingIntent.getBroadcast(c, 11, i,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        if (am != null) {
            am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP,
                    System.currentTimeMillis() + WATCHDOG_MS, pi);
        }
    }

    static void kick(Context c) {
        beat(c);
        armAlarms(c);
    }

    private static void notifyStatus(Context c, boolean reachable) {
        String title = reachable ? "Quant of Rehan: quant is online now."
                : "Quant of Rehan: quant unreachable";
        String text = reachable ? "The relay answered again."
                : "The relay did not answer. Check the PC and the VPN.";
        post(c, CHANNEL_STATUS, "system", 2, title, text);
    }

    private static void notifySignal(Context c, String text) {
        post(c, CHANNEL_SIGNALS, "signals", 5, "Quant of Rehan signal", text);
    }

    /** Market open/close in the owner's own wording (2026-10-08). */
    private static void notifyMarket(Context c, boolean open, String detail) {
        String title = open ? "Market is open. Quant is online now."
                : "Market is closed. Quant is sleeping now.";
        post(c, CHANNEL_STATUS, "market", 3, title,
                detail == null ? "" : detail.trim());
    }

    private static void post(Context c, String channelId, String tag, int id,
                             String title, String text) {
        NotificationManager nm =
                (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm == null) return;
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(new NotificationChannel(channelId,
                    channelId.equals(CHANNEL_STATUS) ? "System status" : "Signals",
                    NotificationManager.IMPORTANCE_DEFAULT));
        }
        android.app.Notification.Builder b =
                new android.app.Notification.Builder(c, channelId)
                        .setSmallIcon(R.drawable.ic_stat_qor)
                        .setContentTitle(title)
                        .setContentText(text)
                        .setStyle(new android.app.Notification.BigTextStyle()
                                .bigText(text))
                        .setAutoCancel(true);
        nm.notify(tag, id, b.build());
    }
}
