package pk.quantofrehan;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
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
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

/**
 * Talks to the relay on the Cloudflare edge, posts notifications, and keeps
 * the watchdog armed. All system questions are answered by the relay; this
 * app never talks to a broker or the exchange and has no chat channel
 * at all (SO-1, SO-9).
 */
public final class Watcher {

    static final String DEFAULT_RELAY =
            "https://quant-of-rehan-relay.mrmrehanqureshi.workers.dev";
    private static final String CHANNEL_STATUS = "system_status";
    private static final String CHANNEL_SIGNALS = "signals";

    // Owner order 2026-10-19 moved the strategy scanner to a one second
    // cadence, so the foreground display poll and the scan now share one
    // number. This class still only reads the relay: it never scans.
    static final long FAST_POLL_MS = 1000;

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

    // Owner order 2026-10-23 (v2.2.1, "why do I need 1 second watch
    // window? if it's not needed anymore then remove it"): the phone-side
    // alarm loop - the phone-side 1s watchdog arm and the PollReceiver it
    // fired - is GONE, and so is the battery-exemption plea that kept it
    // alive. The quant already scans the market every second in the cloud
    // and the relay delivers the feed and signals from there, so a closed
    // app schedules nothing; the handset polls only while it is on screen.

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
     * The health and the card halves of an on-screen tick, raced against each
     * other (owner order 2026-10-22, second report on the same lag: "the
     * numbers move, but not in real time"). Both reads used to run on POOL
     * BACK TO BACK, so every one second tick paid two sequential round trips
     * plus the health retry's own 1.5s sleep, and a single flaky health read
     * pushed every later card read behind it. Each half now owns a thread of
     * its own, so a tick costs one round trip plus the slower of two
     * concurrent reads. Reads only: no write is raced, so nothing on
     * Watcher's state can interleave; the two jobs are joined in this thread,
     * which is POOL's usual single queue of rounds, so two ticks can never
     * overlap.
     */
    private static final ExecutorService HEALTH_POOL =
            Executors.newSingleThreadExecutor();
    private static final ExecutorService CARD_POOL =
            Executors.newSingleThreadExecutor();
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
            Future<Head> headJob = null;
            Future<Market> marketJob = null;
            try {
                headJob = HEALTH_POOL.submit(() -> fetchHead(c, base));
                marketJob = CARD_POOL.submit(() -> fetchMarket(c, base));
                // The relay already merges the live quote hub into /market
                // (applyLiveQuotes in cloud/worker.js), so one answer carries
                // the card, its prices and the index. The extra /quotes read
                // that used to run here cost a third round trip on every
                // one-second tick, which on a phone connection made the
                // console paint every two or three seconds and is exactly the
                // "not moving like a clock" the owner reported on 2026-10-20.
                // The health read is now RACED against this one rather than
                // queued behind it, so a tick costs one round trip, not two
                // stacked ones.
                Head head = headJob.get(20, TimeUnit.SECONDS);
                Market market = marketJob.get(20, TimeUnit.SECONDS);
                cb.done(head.online(), head.reachable, head.detail,
                        head.signals, market);
            } catch (Exception e) {
                // A read that lost its race must never linger with its socket
                // open: cancel both before reporting. Only POOL's own queue
                // can create a new pair, so no racing job can be missed.
                if (headJob != null) {
                    headJob.cancel(true);
                }
                if (marketJob != null) {
                    marketJob.cancel(true);
                }
                Throwable cause = e instanceof ExecutionException
                        && e.getCause() != null ? e.getCause() : e;
                String why = cause.getClass().getSimpleName();
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
     * the slower one: the relay rebuilds it from the cloud capture, though
     * since 2026-10-20 it also merges the live hub into every read, so the
     * card that arrives is current. /quotes is the hub itself: one row per
     * symbol plus the index, each stamped by the broker.
     *
     * This overlay is the fallback the full round keeps (the one-second round
     * no longer pays for the third read). A FRESH index from the snapshot
     * wins, and each leader's price and movement come from its own live quote.
     * A stale row never overwrites a card value: ageing a number forward is
     * the one thing this app must not do (SO-3). If the snapshot is missing or
     * unparseable the card stands on its own, unchanged.
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

            // Owner order 2026-10-20 (second note): the phone rings for four
            // things only, market online, market offline, market break, and a
            // real signal. Relay reachability is therefore recorded silently
            // rather than announced: a flapping connection used to produce a
            // notification each time it came back.
            p.edit().putBoolean("last_reachable", reachable).apply();
            p.edit().putBoolean("last_online", online).apply();
            p.edit().putLong("market_fetched_ms", System.currentTimeMillis()).apply();

            // The market event is the PHASE, not just open/closed, so the
            // midday break gets its own sentence instead of a close followed
            // by an open ten minutes later.
            String event = marketEvent(market);
            if (event != null) {
                String prevEvent = p.getString("last_market_event", "");
                if (prevEvent.isEmpty()) {
                    p.edit().putString("last_market_event", event).apply();
                } else if (!event.equals(prevEvent)) {
                    notifyMarket(c, event, detail);
                    p.edit().putString("last_market_event", event).apply();
                }
            }

            // A card is rewritten every scan with a new slot in its header, so
            // comparing the whole text rang the phone every few seconds even
            // when the verdict never moved. The comparison is the BODY now,
            // and only a body that names a trade is allowed to ring at all.
            String body = signalBody(signals);
            if (!isTradeSignal(body)) {
                return;
            }
            String last = p.getString("last_signal", "");
            if (!body.equals(last)) {
                notifySignal(c, body);
                p.edit().putString("last_signal", body).apply();
            }
        });
    }

    /** The relay's snapshot symbols, sorted. Empty until the first answer. */
    static java.util.List<String> symbols() {
        return SYMBOLS;
    }

    /**
     * One symbol's last price, move and split, for the search rows and the
     * volume dropdowns (owner order 2026-10-23).
     *
     * The relay's own split law computes the buy and sell pair (its frame's
     * day range), so this is only what the answer carried: null means the
     * frame's range was incomplete, never zero (SO-3).
     */
    static final class Quote {
        final double price;
        /** null: the relay has a price but no day's movement for this symbol.
         *  Boxed so the row can print the price in neutral ink instead of
         *  colouring an unknown move as a flat green (SO-3). */
        final Double changePct;
        /** null: the relay's frame had no complete range for the split. */
        final Long buy;
        /** null: the relay's frame had no complete range for the split. */
        final Long sell;

        Quote(double price, Double changePct, Long buy, Long sell) {
            this.price = price;
            this.changePct = changePct;
            this.buy = buy;
            this.sell = sell;
        }
    }

    /**
     * The compact price map, refreshed only while the search panel is open.
     * Empty until the first answer, and a failed refresh keeps the last one.
     */
    private static volatile java.util.Map<String, Quote> PRICES =
            java.util.Collections.emptyMap();

    static Quote quote(String symbol) {
        return PRICES.get(symbol);
    }

    /**
     * The whole price map, for the volume dropdowns (owner order 2026-10-23).
     * Ranking happens in one place, on the map the search already refreshes,
     * so the dropdowns ride the same tick the rows do and cost no request.
     */
    static java.util.Map<String, Quote> quotes() {
        return PRICES;
    }

    interface PricesCallback {
        void done();
    }

    /**
     * Read every published symbol's price and move in one compact answer.
     *
     * The search filters the symbol list locally, so a keystroke costs no
     * request; this map is what lets a row show "PKR 537.00 +0.15%" without
     * asking the relay once per letter. It is read once per foreground tick
     * while the panel is open (owner order 2026-10-20, third note), and the
     * answer is a few kilobytes rather than the whole card.
     *
     * Owner order 2026-10-22: the map is what the CLOSED market's search
     * answers from, so a fresh-only map would erase every price the moment
     * the publisher stops. The relay now answers /prices with each symbol's
     * last published price, whatever its age; nothing is aged forward here,
     * and the selected answer still carries its own stamp through
     * fetchStock. The relay's freshness field also stays in /stock, so a
     * reader of the JSON still knows (SO-3).
     */
    static void fetchPrices(final Context c, final PricesCallback cb) {
        POOL.execute(() -> {
            try {
                JSONObject body = get(relayUrl(c) + "/prices", null);
                JSONArray rows = body.optJSONArray("prices");
                Map<String, Quote> map = new HashMap<>();
                if (rows != null) {
                    for (int i = 0; i < rows.length(); i++) {
                        JSONArray row = rows.optJSONArray(i);
                        if (row == null || row.length() < 3) continue;
                        String symbol = row.optString(0, "");
                        double price = row.optDouble(1, Double.NaN);
                        double pct = row.optDouble(2, Double.NaN);
                        Long buy = null;
                        Long sell = null;
                        Object buyVal = row.opt(3);
                        Object sellVal = row.opt(4);
                        if (buyVal instanceof Number) {
                            buy = ((Number) buyVal).longValue();
                        }
                        if (sellVal instanceof Number) {
                            sell = ((Number) sellVal).longValue();
                        }
                    if (!symbol.isEmpty() && !Double.isNaN(price) && price > 0) {
                        map.put(symbol, new Quote(price,
                                Double.isNaN(pct) ? null : pct, buy, sell));
                    }
                }
            }
            // Owner order 2026-10-22: an answer that carries no row keeps
            // the map that is on screen. A closed market's snapshot names
            // every scrip it ever published, but a publisher caught between
            // two pushes could answer with none, and one empty answer
            // blanking the rows for a tick is the visible flicker the
            // search's stability law (owner report 2026-10-20) never
            // approved.
            PRICES = map.isEmpty() && !PRICES.isEmpty()
                    ? PRICES
                    : java.util.Collections.unmodifiableMap(map);
                // The search's universe comes from the same answer, so the
                // list exists even before the first full round.
                if (!map.isEmpty()) {
                    java.util.List<String> names = new java.util.ArrayList<>(map.keySet());
                    java.util.Collections.sort(names);
                    SYMBOLS = java.util.Collections.unmodifiableList(names);
                }
            } catch (Exception ignored) {
                // Keep the last map: a stale price with its own stamp is
                // better than a row that loses its colour on one timeout.
            }
            cb.done();
        });
    }        interface StockCallback {
        void done(boolean ok, android.text.SpannableString line);
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
                    cb.done(false, null);
                    return;
                }
                StringBuilder sb = new StringBuilder(row.optString("symbol", symbol));
                Double buy = numberOrNull(row, "buy_volume");
                Double sell = numberOrNull(row, "sell_volume");
                Double total = numberOrNull(row, "volume");
                android.text.SpannableString styled = null;
                if (buy != null && sell != null) {
                    // Owner order 2026-10-20 (third note): the EST tag after
                    // the total is gone from the search answer exactly as it
                    // is from the card. The numbers are the numbers, and the
                    // relay still labels the method in split_source for
                    // anyone reading the JSON (SO-3).
                    // Owner order 2026-10-21: the buy count prints green and
                    // the sell count red, the digits themselves, and the
                    // spans travel with the line so the one-second restamp
                    // keeps them. The money line is not built here any
                    // more: paintSelectedLine restamps the live quote's own
                    // price and percentage onto this same line every tick,
                    // so the copy that lived here was the second print of
                    // the same numbers and is retired.
                    //
                    // v2.3.19 owner order ("in the search box, there should
                    // be , after B and & after S" and "In the search results
                    // I think there are double spacing, so you remove
                    // that"): the separators are the leaders card's own now.
                    // One space after the symbol, a comma after the B digits,
                    // an ampersand after the S digits, each group held by ONE
                    // space - never the double spaces the line carried
                    // before, which read as a broken bracket and printed the
                    // search answer with gaps the card's own shape never
                    // has.
                    sb.append(" (B=");
                    int buyFrom = sb.length();
                    sb.append(String.format(java.util.Locale.US, "%,.0f", buy));
                    int buyTo = sb.length();
                    sb.append(", S=");
                    int sellFrom = sb.length();
                    sb.append(String.format(java.util.Locale.US, "%,.0f", sell));
                    int sellTo = sb.length();
                    if (total != null) {
                        sb.append(String.format(java.util.Locale.US, " & T=%,.0f", total));
                    }
                    sb.append(')');
                    styled = new android.text.SpannableString(sb);
                    styled.setSpan(new android.text.style.ForegroundColorSpan(
                            c.getColor(R.color.green)), buyFrom, buyTo, 0);
                    styled.setSpan(new android.text.style.ForegroundColorSpan(
                            c.getColor(R.color.red)), sellFrom, sellTo, 0);
                } else if (total != null) {
                    sb.append(String.format(java.util.Locale.US, " (T=%,.0f)", total));
                    styled = new android.text.SpannableString(sb);
                } else {
                    styled = new android.text.SpannableString(sb);
                }
                cb.done(true, styled);
            } catch (Exception e) {
                cb.done(false, null);
            }
        });
    }

    static void kick(Context c) {
        beat(c);
    }

    private static void notifySignal(Context c, String text) {
        post(c, CHANNEL_SIGNALS, "signals", 5, "Quant of Rehan signal", text);
    }

    /**
     * The market event a phase stands for, or null for a phase the owner did
     * not ask to hear about (pre-open, halted, unknown).
     */
    private static String marketEvent(Market market) {
        if (market == null || market.phase == null) {
            return null;
        }
        switch (market.phase) {
            case "OPEN":
                return "online";
            case "BREAK":
                return "break";
            case "CLOSED":
            case "POST_CLOSE":
                return "offline";
            default:
                return null;
        }
    }

    /** Market online, offline and break in the owner's own wording. */
    private static void notifyMarket(Context c, String event, String detail) {
        int title;
        if ("online".equals(event)) {
            title = R.string.market_open_notification;
        } else if ("break".equals(event)) {
            title = R.string.market_break_notification;
        } else {
            title = R.string.market_closed_notification;
        }
        post(c, CHANNEL_STATUS, "market", 3, c.getString(title),
                detail == null ? "" : detail.trim());
    }

    /** The card without its dated header, which changes every scan. */
    private static String signalBody(String text) {
        if (text == null) {
            return "";
        }
        int newline = text.indexOf('\n');
        return (newline >= 0 ? text.substring(newline + 1) : text).trim();
    }

    /**
     * Is this body a trade, rather than a no-trade state or an informational
     * note? Only a trade may ring the phone (owner order 2026-10-20).
     */
    private static boolean isTradeSignal(String body) {
        if (body == null || body.isEmpty()) {
            return false;
        }
        String upper = body.toUpperCase(java.util.Locale.US);
        if (upper.startsWith("NO TRADE") || upper.startsWith("NO SIGNAL")
                || upper.startsWith("NO CALL") || upper.contains("NO SIGNAL AVAILABLE")) {
            return false;
        }
        return upper.contains("SYMBOL:") || upper.contains("ENTERED AT");
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
