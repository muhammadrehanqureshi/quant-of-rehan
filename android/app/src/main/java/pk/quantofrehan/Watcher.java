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
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
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

    // owner order 2026-10-09: the app refreshes the index and the volume
    // leaders every 5 minutes (was 15)
    static final long REFRESH_MS = 5 * 60 * 1000;

    private static final ExecutorService POOL = Executors.newSingleThreadExecutor();

    private Watcher() {
    }

    /** What the app knows about the exchange at this instant. */
    static final class Market {
        boolean answered;
        boolean open;
        double indexValue = Double.NaN;
        double indexChange;
        double indexPct;
        String indexAsOf = "";
        int members;
        /** symbol, volume, price for the day's most traded index members. */
        final List<String[]> leaders = new ArrayList<>();
        String basis = "";
        String note = "";
        int cacheAgeSeconds = -1;

        boolean hasIndex() {
            return !Double.isNaN(indexValue);
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

    /** One raw GET; returns the parsed body or throws. */
    private static JSONObject get(String url, String admin) throws Exception {
        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        conn.setConnectTimeout(8000);
        conn.setReadTimeout(12000);
        if (admin != null && !admin.isEmpty()) {
            conn.setRequestProperty("x-admin-token", admin);
        }
        BufferedReader r = new BufferedReader(new InputStreamReader(
                conn.getResponseCode() >= 400 ? conn.getErrorStream()
                        : conn.getInputStream(),
                StandardCharsets.UTF_8));
        StringBuilder sb = new StringBuilder();
        String line;
        while ((line = r.readLine()) != null) {
            sb.append(line);
        }
        r.close();
        return new JSONObject(sb.toString());
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
     * The relay's market card: KSE100 and the day's volume leaders, rebuilt
     * at most once every five minutes by the relay itself. A failure here
     * never changes the status badge, it only empties the card.
     */
    static Market fetchMarket(String base) {
        Market market = new Market();
        try {
            JSONObject body = get(base + "/market", null);
            market.answered = body.optBoolean("ok", false);
            market.open = body.optBoolean("market_open", false);
            market.cacheAgeSeconds = body.optInt("cache_age_seconds", -1);
            market.members = body.optInt("kmiall_members", 0);
            market.basis = body.optString("top_volume_basis", "");

            JSONObject index = body.optJSONObject("index");
            if (index != null) {
                market.indexValue = index.optDouble("value", Double.NaN);
                market.indexChange = index.optDouble("change", 0);
                market.indexPct = index.optDouble("change_pct", 0);
                market.indexAsOf = index.optString("as_of", "");
            }

            JSONArray tops = body.optJSONArray("top_volume");
            if (tops != null) {
                for (int i = 0; i < tops.length() && i < 3; i++) {
                    JSONObject row = tops.optJSONObject(i);
                    if (row == null) continue;
                    market.leaders.add(new String[]{
                            row.optString("symbol", ""),
                            String.valueOf(row.optLong("volume", 0)),
                            row.isNull("price") ? "" : String.valueOf(row.optDouble("price")),
                    });
                }
            }
            JSONArray notes = body.optJSONArray("notes");
            if (notes != null && notes.length() > 0) {
                market.note = notes.optString(0, "");
            }
            if (body.optBoolean("stale", false)) {
                market.note = "relay last refreshed earlier: " + market.note;
            }
        } catch (Exception e) {
            market.note = "Market card could not load (" + e.getClass().getSimpleName() + ").";
        }
        return market;
    }

    /**
     * One fetch round. ONLINE means a live session AND a relay that answers.
     * The owner's rule (2026-10-09): when the market is closed the app must
     * say OFFLINE with a red cross, never ONLINE.
     */
    static void fetchStatus(final Context c, final String admin, final Callback cb) {
        POOL.execute(() -> {
            String base = relayUrl(c);
            try {
                JSONObject health = healthWithRetry(base);
                boolean reachable = health.optBoolean("ok", false);
                boolean marketOpen = health.optBoolean("market_open", false);
                String karachi = health.optString("karachi_now", "");
                boolean online = reachable && marketOpen;

                // owner order 2026-10-07: the app shows only the Karachi
                // clock; the next-event line is gone
                String detail;
                if (!reachable) {
                    detail = "The relay answered but reported a fault.";
                } else if (marketOpen) {
                    detail = "Karachi: " + karachi;
                } else {
                    detail = "Karachi: " + karachi
                            + "\nPSX session closed. Quant is sleeping.";
                }

                String signals = "";
                String signalNote = "";
                if (!admin.isEmpty()) {
                    try {
                        JSONObject sig = get(base + "/signals", admin);
                        if (sig.optBoolean("ok")) {
                            signals = sig.optString("signals", "");
                        } else {
                            signalNote = "The relay rejected the token. Paste the current admin token (gear icon).";
                        }
                    } catch (Exception se) {
                        signalNote = "Signals could not load just now.";
                    }
                }
                if (!signalNote.isEmpty() && signals.trim().isEmpty()) {
                    signals = signalNote;
                }
                cb.done(online, reachable, detail, signals, fetchMarket(base));
            } catch (Exception e) {
                String why = e.getClass().getSimpleName();
                String hint = why.contains("UnknownHost") || why.contains("Connect")
                        ? "No route to the relay from this phone. Check internet or VPN."
                        : "The relay did not answer in time. Will retry.";
                Market market = new Market();
                market.note = "Relay unreachable, so the market card is empty.";
                cb.done(false, false, hint + " (" + why + ")", "", market);
            }
        });
    }

    /** Watchdog beat: fetch, compare, notify on change or on signals. */
    static void beat(final Context c) {
        final String admin = prefs(c).getString("admin_token", "");
        fetchStatus(c, admin, (online, reachable, detail, signals, market) -> {
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

    static void armAlarms(Context c) {
        AlarmManager am = (AlarmManager) c.getSystemService(Context.ALARM_SERVICE);
        Intent i = new Intent(c, PollReceiver.class);
        PendingIntent pi = PendingIntent.getBroadcast(c, 11, i,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        if (am != null) {
            am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP,
                    System.currentTimeMillis() + REFRESH_MS, pi);
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
