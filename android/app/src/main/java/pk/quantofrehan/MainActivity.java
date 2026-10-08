package pk.quantofrehan;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.widget.EditText;
import android.widget.TextView;
import android.widget.Toast;

/**
 * Quant of Rehan owner console. One glance: is the system online, and is
 * there a signal. Settings (token, watchdog) hide behind the gear.
 *
 * Brand law (owner order, 2026-10-06): the gear button is neutral plum in
 * every state and wears its gold ring ONLY while the settings panel is
 * open. All chrome comes from the official logo palette.
 */
public class MainActivity extends Activity {

    private SharedPreferences prefs;
    private TextView statusPill, statusDetail, signalList;
    private TextView btnSettings;
    private View settingsPanel;
    private android.graphics.Typeface scriptFont;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences("qor", MODE_PRIVATE);
        setContentView(R.layout.activity_main);

        // the owner's chosen face for the motivation quote: FSP DEMO - Liana
        // (free demo download, bundled as res/font/fsp_demo_liana.otf).
        scriptFont = getResources().getFont(R.font.fsp_demo_liana);
        ((TextView) findViewById(R.id.motivation_text)).setTypeface(scriptFont);

        statusPill = findViewById(R.id.status_pill);
        statusDetail = findViewById(R.id.status_detail);
        signalList = findViewById(R.id.signal_list);
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
            toast("Watchdog armed. Status pings every 15 minutes.");
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
        Watcher.fetchStatus(this, admin, (online, detail, signals) ->
                runOnUiThread(() -> render(online, detail, signals)));
    }

    private void render(boolean online, String detail, String signals) {
        GradientDrawable bg = new GradientDrawable();
        bg.setCornerRadius(dp(18));
        bg.setColor(getColor(online ? R.color.green_soft : R.color.red_soft));
        bg.setStroke(dp(1), getColor(online ? R.color.green : R.color.red));
        statusPill.setBackground(bg);
        // the owner's marker law: a green check on ONLINE, a red cross on
        // OFFLINE (the round dot is retired)
        statusPill.setText(online ? "✓  ONLINE" : "✗  OFFLINE");
        statusPill.setTextColor(getColor(online
                ? R.color.green : R.color.red));

        String d = detail == null ? "" : detail.trim();
        if (d.isEmpty()) {
            statusDetail.setText(getString(R.string.checking));
        } else {
            // "Karachi: <clock> | Next: <event>" -> the clock gets the
            // brand teal, monospaced, like a terminal readout
            android.text.SpannableString sp = new android.text.SpannableString(d);
            int k = d.indexOf("Karachi: ");
            if (k >= 0) {
                int start = k + "Karachi: ".length();
                int end = start;
                while (end < d.length() && d.charAt(end) != '|'
                        && d.charAt(end) != '\n') {
                    end++;
                }
                sp.setSpan(new android.text.style.StyleSpan(Typeface.BOLD),
                        start, Math.min(end, d.length()), 0);
                sp.setSpan(new android.text.style.ForegroundColorSpan(
                                getColor(R.color.teal_bright)),
                        start, Math.min(end, d.length()), 0);
                sp.setSpan(new android.text.style.TypefaceSpan("monospace"),
                        start, Math.min(end, d.length()), 0);
            }
            statusDetail.setText(sp);
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
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show();
    }

    private int dp(int v) {
        return (int) (getResources().getDisplayMetrics().density * v);
    }
}
