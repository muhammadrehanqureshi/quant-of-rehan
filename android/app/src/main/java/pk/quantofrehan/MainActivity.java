package pk.quantofrehan;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.text.SpannableString;
import android.text.style.ForegroundColorSpan;
import android.text.style.StyleSpan;
import android.text.style.TypefaceSpan;
import android.view.View;
import android.widget.EditText;
import android.widget.TextView;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Quant of Rehan owner console. One glance: is the system online, is there a
 * signal, and where is the market. Settings hide behind the gear.
 *
 * Brand law (owner order, 2026-10-06): the gear button is neutral plum in
 * every state and wears its gold ring ONLY while the settings panel is
 * open. All chrome comes from the official logo palette.
 *
 * Owner order 2026-10-09: the motivation quote is retired, and its place is
 * taken by a third card showing the KSE100 index and the day's top three
 * KMIALL stocks by volume, plus the rule that a closed market shows OFFLINE
 * with a red cross.
 *
 * Owner order 2026-10-11: the checkmark and the cross are retired. ONLINE and
 * OFFLINE are shown as a vector status light beside the word
 * (drawable/ic_status_online and ic_status_offline), the volume leaders carry
 * their labelled buy and sell volumes, the scan cadence is pinned to the
 * bottom of the interface, and the legacy lines about index membership and a
 * broker capture are gone. Every sentence still comes from a string resource,
 * so the copy, the accessibility description and the layout cannot drift.
 */
public class MainActivity extends Activity {

    private SharedPreferences prefs;
    private TextView statusPill, statusDetail, signalList;
    private TextView marketIndex, marketLeaders, marketFoot;
    private TextView btnSettings;
    private View settingsPanel;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences("qor", MODE_PRIVATE);
        setContentView(R.layout.activity_main);

        statusPill = findViewById(R.id.status_pill);
        statusDetail = findViewById(R.id.status_detail);
        signalList = findViewById(R.id.signal_list);
        marketIndex = findViewById(R.id.market_index);
        marketLeaders = findViewById(R.id.market_leaders);
        marketFoot = findViewById(R.id.market_foot);
        settingsPanel = findViewById(R.id.settings_panel);
        btnSettings = findViewById(R.id.btn_settings);

        final EditText tokenBox = findViewById(R.id.token_box);
        tokenBox.setText(prefs.getString("admin_token", ""));

        btnSettings.setOnClickListener(v -> {
            boolean show = settingsPanel.getVisibility() == View.GONE;
            settingsPanel.setVisibility(show ? View.VISIBLE : View.GONE);
            // the ring follows the panel state, never anything else
            btnSettings.setBackgroundResource(show
                    ? R.drawable.gear_bg_open : R.drawable.gear_bg);
        });

        findViewById(R.id.btn_save).setOnClickListener(v -> {
            String t = tokenBox.getText().toString().trim();
            prefs.edit().putString("admin_token", t).apply();
            toast(t.isEmpty() ? "Token cleared." : "Token saved.");
            settingsPanel.setVisibility(View.GONE);
            btnSettings.setBackgroundResource(R.drawable.gear_bg);
            Watcher.kick(this);
            refresh();
        });

        findViewById(R.id.btn_open).setOnClickListener(v -> {
            String url = prefs.getString("relay_url", Watcher.DEFAULT_RELAY);
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url + "/health")));
        });

        findViewById(R.id.btn_arm).setOnClickListener(v -> {
            Watcher.armAlarms(this);
            maybeRequestBatteryExemption(true);
            toast("Watchdog armed. Refreshing every 5 minutes.");
        });

        Watcher.kick(this);
        // v1.5.1: ask once, quietly, so Doze and OEM battery managers do not
        // defer the watchdog. The Arm button can always ask again on demand.
        maybeRequestBatteryExemption(false);
    }

    /**
     * A 5 minute watchdog on Android is best effort: setExactAndAllowWhileIdle
     * is capped inside Doze and some OEM battery managers stop the app
     * entirely. A battery optimisation exemption is the one thing an app can
     * ask for, so ask for it. Never nag: the first run asks once and the Arm
     * button asks again only because the owner pressed it.
     */
    private void maybeRequestBatteryExemption(boolean byOwner) {
        android.os.PowerManager pm =
                (android.os.PowerManager) getSystemService(POWER_SERVICE);
        if (pm == null || pm.isIgnoringBatteryOptimizations(getPackageName())) {
            return; // already exempt: nothing to ask for
        }
        if (!byOwner && prefs.getBoolean("asked_battery", false)) {
            return;
        }
        prefs.edit().putBoolean("asked_battery", true).apply();
        try {
            startActivity(new Intent(
                    android.provider.Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                    Uri.parse("package:" + getPackageName())));
        } catch (Exception e) {
            toast("Allow the battery exemption so the watchdog is never frozen.");
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        refresh();
    }

    private void refresh() {
        String admin = prefs.getString("admin_token", "");
        Watcher.fetchStatus(this, admin, (online, reachable, detail, signals, market) ->
                runOnUiThread(() -> render(online, detail, signals, market)));
    }

    private void render(boolean online, String detail, String signals,
                        Watcher.Market market) {
        GradientDrawable bg = new GradientDrawable();
        bg.setCornerRadius(dp(18));
        bg.setColor(getColor(online ? R.color.green_soft : R.color.red_soft));
        bg.setStroke(dp(1), getColor(online ? R.color.green : R.color.red));
        statusPill.setBackground(bg);
        // The owner's marker law, 2026-10-11: one status light beside the
        // word, lit for ONLINE and hollow for OFFLINE, so the badge reads as
        // an indicator rather than as an emoji. A shut session is OFFLINE.
        statusPill.setCompoundDrawablesRelativeWithIntrinsicBounds(online
                ? R.drawable.ic_status_online : R.drawable.ic_status_offline,
                0, 0, 0);
        statusPill.setText(getString(online
                ? R.string.status_online : R.string.status_offline));
        statusPill.setTextColor(getColor(online
                ? R.color.green : R.color.red));
        // Material accessibility: the pill is a live state indicator, so it
        // announces itself and carries a spoken description. A glyph alone
        // reads as "multiplication X" to a screen reader.
        statusPill.setContentDescription(getString(online
                ? R.string.cd_status_online : R.string.cd_status_offline));

        String d = detail == null ? "" : detail.trim();
        if (d.isEmpty()) {
            statusDetail.setText(getString(R.string.checking));
        } else {
            statusDetail.setText(clockSpans(d));
        }

        String s = signals == null ? "" : signals.trim();
        if (s.isEmpty()) {
            signalList.setText(getString(R.string.no_signals));
            signalList.setTextColor(getColor(R.color.text_soft));
            signalList.setAlpha(0.65f);
        } else {
            signalList.setText(s);
            signalList.setTextColor(getColor(R.color.text_bright));
            signalList.setAlpha(1.0f);
        }

        renderMarket(market);
    }

    /** "Karachi: <clock>" gets the brand teal, monospaced, terminal style. */
    private SpannableString clockSpans(String d) {
        SpannableString sp = new SpannableString(d);
        int k = d.indexOf("Karachi: ");
        if (k >= 0) {
            int start = k + "Karachi: ".length();
            int end = start;
            while (end < d.length() && d.charAt(end) != '|'
                    && d.charAt(end) != '\n') {
                end++;
            }
            end = Math.min(end, d.length());
            sp.setSpan(new StyleSpan(Typeface.BOLD), start, end, 0);
            sp.setSpan(new ForegroundColorSpan(getColor(R.color.teal_bright)),
                    start, end, 0);
            sp.setSpan(new TypefaceSpan("monospace"), start, end, 0);
        }
        return sp;
    }

    /** The third card: index points and the day's volume leaders. */
    private void renderMarket(Watcher.Market market) {
        if (market == null) {
            marketIndex.setText(getString(R.string.market_waiting));
            marketLeaders.setText(getString(R.string.market_leaders_waiting));
            marketFoot.setText("");
            return;
        }

        if (market.hasIndex()) {
            // hasIndex() guarantees all three are non-null, so the unboxing
            // below cannot throw. A half-reported index renders as waiting
            // instead of as a zero.
            String line = String.format(Locale.US, "KSE100  %,.2f   %s %,.2f (%.2f%%)",
                    market.indexValue,
                    market.indexChange >= 0 ? "\u25B2" : "\u25BC",
                    Math.abs(market.indexChange),
                    Math.abs(market.indexPct));
            SpannableString sp = new SpannableString(line);
            int color = getColor(market.indexChange >= 0
                    ? R.color.green : R.color.red);
            int from = line.indexOf(market.indexChange >= 0 ? "\u25B2" : "\u25BC");
            if (from >= 0) {
                sp.setSpan(new ForegroundColorSpan(color), from, line.length(), 0);
            }
            marketIndex.setText(sp);
        } else {
            marketIndex.setText(getString(R.string.market_waiting));
        }

        List<Watcher.Leader> leaders = market.leaders;
        if (leaders.isEmpty()) {
            if (!market.answered) {
                marketLeaders.setText(getString(R.string.market_leaders_waiting));
            } else if (market.basis.contains("has traded yet")) {
                marketLeaders.setText(getString(R.string.market_none_yet));
            } else {
                marketLeaders.setText(getString(R.string.market_unavailable));
            }
        } else {
            marketLeaders.setText(leadersText(leaders));
        }

        marketFoot.setText(footText(market, leaders.size()));
    }

    /**
     * "1. ABC   B=12,345  S=9,876  T=22,221   Rs 12.52   green 1.05%"
     *
     * The buy and sell volumes are the owner's request of 2026-10-10, now
     * always shown for the top three when the relay reports them: buying is
     * green, selling is red, the total stays neutral, so the two sides read
     * apart before the digits do.
     *
     * What the numbers MEAN travels in the card's footnote, never in the row:
     * the relay says whether they were measured from the session tape or
     * estimated from the day's range (SO-3).
     *
     * Every field is a boxed Number, so a null means the relay did not report
     * it and the field is skipped rather than printed as a zero.
     */
    private SpannableString leadersText(List<Watcher.Leader> leaders) {
        StringBuilder sb = new StringBuilder();
        List<int[]> spans = new ArrayList<>();   // {from, to, colour resource}
        for (int i = 0; i < leaders.size(); i++) {
            Watcher.Leader row = leaders.get(i);
            if (i > 0) {
                sb.append('\n');
            }
            sb.append(String.format(Locale.US, "%d. %s", i + 1, row.symbol));
            if (row.hasSplit()) {
                sb.append("   B=");
                int buyFrom = sb.length();
                sb.append(String.format(Locale.US, "%,d", row.buy));
                spans.add(new int[]{buyFrom, sb.length(), R.color.green});
                sb.append("  S=");
                int sellFrom = sb.length();
                sb.append(String.format(Locale.US, "%,d", row.sell));
                spans.add(new int[]{sellFrom, sb.length(), R.color.red});
                sb.append(String.format(Locale.US, "  T=%,d", row.volume));
            } else if (row.hasVolume()) {
                sb.append(String.format(Locale.US, "   T=%,d", row.volume));
            }
            if (row.price != null) {
                sb.append(String.format(Locale.US, "   Rs %,.2f", row.price));
            }
            if (row.changePct != null) {
                int from = sb.length();
                sb.append(String.format(Locale.US, "   %s %.2f%%",
                        row.changePct >= 0 ? "\u25B2" : "\u25BC",
                        Math.abs(row.changePct)));
                spans.add(new int[]{from, sb.length(), row.changePct >= 0
                        ? R.color.green : R.color.red});
            }
        }
        SpannableString sp = new SpannableString(sb.toString());
        for (int[] span : spans) {
            sp.setSpan(new ForegroundColorSpan(getColor(span[2])),
                    span[0], span[1], 0);
        }
        return sp;
    }

    /**
     * The card's footnote, built from what actually arrived.
     *
     * Owner order 2026-10-11: the legacy sentences are gone. Nothing names an
     * index membership or a capture process any more. The ranking sentence
     * states the basis, the relay's split sentence states how the buy and
     * sell numbers were produced (measured or estimated), and a failure is
     * still reported in the relay's own words.
     *
     * The session sentence is deliberately NOT repeated here: it belongs to
     * the status card above, and saying it twice made this line read as
     * noise. It lives in exactly one place, Watcher.phaseLine.
     */
    private String footText(Watcher.Market market, int shown) {
        StringBuilder foot = new StringBuilder();
        if (!market.indexAsOf.isEmpty()) {
            foot.append("Index as of ").append(market.indexAsOf).append(" PKT");
        }
        String basis = market.basis == null ? "" : market.basis.trim();
        if (basis.isEmpty() && shown > 0) {
            // The relay normally sends its own basis sentence; this states the
            // same fact from the same row count when it does not.
            basis = String.format(Locale.US,
                    "current session volume, top %d", shown);
        }
        appendPart(foot, basis);
        appendPart(foot, market.splitBasis == null ? "" : market.splitBasis.trim());
        if (market.note != null && !market.note.trim().isEmpty()) {
            foot.append(foot.length() > 0 ? "\n" : "").append(market.note.trim());
        }
        return foot.toString();
    }

    private void appendPart(StringBuilder foot, String part) {
        if (part == null || part.trim().isEmpty()) {
            return;
        }
        foot.append(foot.length() > 0 ? " · " : "").append(part.trim());
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show();
    }

    private int dp(int v) {
        return (int) (getResources().getDisplayMetrics().density * v);
    }
}
