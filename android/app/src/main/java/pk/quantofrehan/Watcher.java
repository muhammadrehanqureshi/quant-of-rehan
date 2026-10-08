package pk.quantofrehan;

import android.app.AlarmManager;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Talks to the relay on the Cloudflare edge, posts notifications, and keeps
 * the 15-minute watchdog armed. All system questions are answered by the
 * relay; this app never talks to Telegram or the broker (SO-1, SO-9).
 */
public final class Watcher {

    static final String DEFAULT_RELAY =
            "https://quant-of-rehan-relay.mrmrehanqureshi.workers.dev";
    private static final String CHANNEL_STATUS = "system_status";
    private static final String CHANNEL_SIGNALS = "signals";
    private static final long WATCHDOG_MS = 15 * 60 * 1000;

    private static final ExecutorService POOL = Executors.newSingleThreadExecutor();

    private Watcher() {
    }

    interface Callback {
        void done(boolean online, String detail, String signals);
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
     * One fetch round. ONLINE means the relay answered /health; the signals
     * call never flips the status, it only fills or empties the signal card.
     */
    static void fetchStatus(final Context c, final String admin, final Callback cb) {
        POOL.execute(() -> {
            String base = relayUrl(c);
            try {
                JSONObject health = healthWithRetry(base);
                boolean online = health.optBoolean("ok", false);
                String karachi = health.optString("karachi_now", "");
                // owner order 2026-10-07: the app shows only the Karachi
                // clock; the next-event line is gone
                String detail = online
                        ? "Karachi: " + karachi
                        : "The relay answered but reported a fault.";

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
                cb.done(online, detail, signals);
            } catch (Exception e) {
                String why = e.getClass().getSimpleName();
                String hint = why.contains("UnknownHost") || why.contains("Connect")
                        ? "No route to the relay from this phone. Check internet or VPN."
                        : "The relay did not answer in time. Will retry.";
                cb.done(false, hint + " (" + why + ")", "");
            }
        });
    }

    /** Watchdog beat: fetch, compare, notify on change or on signals. */
    static void beat(final Context c) {
        final String admin = prefs(c).getString("admin_token", "");
        fetchStatus(c, admin, (online, detail, signals) -> {
            SharedPreferences p = prefs(c);
            boolean was = p.getBoolean("last_online", false);
            if (online != was) {
                notifyStatus(c, online, detail);
                p.edit().putBoolean("last_online", online).apply();
            } else if (online) {
                // quiet heartbeat: refresh the "still working" timestamp only
                p.edit().putLong("last_seen_ms", System.currentTimeMillis()).apply();
            }

            // owner order 2026-10-08: the app must send EVERY notification,
            // including market open and close, not only relay up/down. The
            // market state is derived from the relay's Karachi clock (PSX
            // session: Mon-Fri 09:30-15:30 PKT, PKT is fixed UTC+5).
            if (online) {
                int mkt = marketState(detail);
                if (mkt >= 0) {
                    int prev = p.getInt("last_market_open", -1);
                    if (prev == -1) {
                        // first reading after install: record silently
                        p.edit().putInt("last_market_open", mkt).apply();
                    } else if (mkt != prev) {
                        notifyMarket(c, mkt == 1, detail);
                        p.edit().putInt("last_market_open", mkt).apply();
                    }
                }
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

    /**
     * PSX market state from the detail line's Karachi clock
     * ("Karachi: 2026-10-08 10:48 PKT"). Returns 1 open, 0 closed, -1 when
     * the clock cannot be parsed. No java.time (API 24 floor): the day of
     * week comes from Sakamoto's method.
     */
    static int marketState(String detail) {
        if (detail == null) return -1;
        int k = detail.indexOf("Karachi: ");
        if (k < 0) return -1;
        String s = detail.substring(k + "Karachi: ".length()).trim();
        try {
            int y = Integer.parseInt(s.substring(0, 4));
            int mo = Integer.parseInt(s.substring(5, 7));
            int d = Integer.parseInt(s.substring(8, 10));
            int hh = Integer.parseInt(s.substring(11, 13));
            int mm = Integer.parseInt(s.substring(14, 16));
            int[] t = {0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4};
            int yy = mo < 3 ? y - 1 : y;
            int dow = (yy + yy / 4 - yy / 100 + yy / 400 + t[mo - 1] + d) % 7;
            if (dow == 0 || dow == 6) return 0; // Sun/Sat: closed
            int mins = hh * 60 + mm;
            return (mins >= 9 * 60 + 30 && mins < 15 * 60 + 30) ? 1 : 0;
        } catch (Exception e) {
            return -1;
        }
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

    private static void notifyStatus(Context c, boolean online, String detail) {
        String title = online ? "Quant of Rehan: quant is online now."
                : "Quant of Rehan: quant unreachable";
        String text = online ? detail
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
