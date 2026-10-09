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
            toast("Watchdog armed. Refreshing every 5 minutes.");
        });

        Watcher.kick(this);
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
        // the owner's marker law: a green check on ONLINE, a red cross on
        // OFFLINE (the round dot is retired). A closed session is OFFLINE.
        statusPill.setText(online ? "✓  ONLINE" : "✗  OFFLINE");
        statusPill.setTextColor(getColor(online
                ? R.color.green : R.color.red));

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
            String line = String.format(Locale.US, "KSE100  %,.2f   %s %,.2f (%.2f%%)",
                    market.indexValue,
                    market.indexChange >= 0 ? "▲" : "▼",
                    Math.abs(market.indexChange),
                    Math.abs(market.indexPct));
            SpannableString sp = new SpannableString(line);
            int color = getColor(market.indexChange >= 0
                    ? R.color.green : R.color.red);
            int from = line.indexOf(market.indexChange >= 0 ? "▲" : "▼");
            if (from >= 0) {
                sp.setSpan(new ForegroundColorSpan(color), from, line.length(), 0);
            }
            marketIndex.setText(sp);
        } else {
            marketIndex.setText(getString(R.string.market_waiting));
        }

        List<String[]> leaders = market.leaders;
        if (leaders.isEmpty()) {
            if (!market.answered) {
                marketLeaders.setText(getString(R.string.market_leaders_waiting));
            } else if (market.basis.contains("has traded yet")) {
                marketLeaders.setText(getString(R.string.market_none_yet));
            } else {
                marketLeaders.setText(getString(R.string.market_unavailable));
            }
        } else {
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < leaders.size(); i++) {
                String[] row = leaders.get(i);
                long volume;
                try {
                    volume = Long.parseLong(row[1]);
                } catch (NumberFormatException nfe) {
                    volume = 0;
                }
                if (i > 0) sb.append('\n');
                sb.append(String.format(Locale.US, "%d. %s   %,d shares",
                        i + 1, row[0], volume));
                if (row[2] != null && !row[2].isEmpty()) {
                    try {
                        sb.append(String.format(Locale.US, "   Rs %,.2f",
                                Double.parseDouble(row[2])));
                    } catch (NumberFormatException ignored) {
                        // price is optional decoration; volume is the ranking
                    }
                }
            }
            marketLeaders.setText(sb.toString());
        }

        StringBuilder foot = new StringBuilder();
        if (!market.indexAsOf.isEmpty()) {
            foot.append("Index as of ").append(market.indexAsOf).append(" PKT");
        }
        if (market.members > 0) {
            foot.append(foot.length() > 0 ? " · " : "")
                    .append("volume: today, top of ").append(market.members)
                    .append(" KMIALLSHR members");
        }
        if (!market.open) {
            foot.append(foot.length() > 0 ? " · " : "")
                    .append("session closed");
        }
        if (!market.note.isEmpty()) {
            foot.append(foot.length() > 0 ? "\n" : "").append(market.note);
        }
        marketFoot.setText(foot.toString());
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show();
    }

    private int dp(int v) {
        return (int) (getResources().getDisplayMetrics().density * v);
    }
}
