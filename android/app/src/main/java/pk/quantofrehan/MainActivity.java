package pk.quantofrehan;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;
import android.widget.Toast;

/**
 * Quant of Rehan owner console. Dark and gold, from the logo. Shows the
 * live system verdict from the relay, stores the admin token for signal
 * polling, and arms the 15-minute watchdog.
 */
public class MainActivity extends Activity {

    private SharedPreferences prefs;
    private TextView statusPill, statusTitle, statusDetail, signalList;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences("qor", MODE_PRIVATE);
        setContentView(R.layout.activity_main);

        statusPill = findViewById(R.id.status_pill);
        statusTitle = findViewById(R.id.status_title);
        statusDetail = findViewById(R.id.status_detail);
        signalList = findViewById(R.id.signal_list);

        final EditText tokenBox = findViewById(R.id.token_box);
        tokenBox.setText(prefs.getString("admin_token", ""));

        findViewById(R.id.btn_save).setOnClickListener(v -> {
            String t = tokenBox.getText().toString().trim();
            prefs.edit().putString("admin_token", t).apply();
            toast(t.isEmpty() ? "Token cleared." : "Token saved. Polling signals.");
            StatusService.kick(this);
            refresh();
        });

        findViewById(R.id.btn_open).setOnClickListener(v -> {
            String url = prefs.getString("relay_url", StatusService.DEFAULT_RELAY);
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url + "/health")));
        });

        findViewById(R.id.btn_arm).setOnClickListener(v -> {
            StatusService.armAlarms(this);
            toast("Watchdog armed. Status pings every 15 minutes.");
        });

        StatusService.kick(this);
    }

    @Override
    protected void onResume() {
        super.onResume();
        refresh();
    }

    private void refresh() {
        String admin = prefs.getString("admin_token", "");
        StatusService.fetchStatus(this, admin, (online, detail, signals) -> {
            render(online, detail, signals);
        });
    }

    private void render(boolean online, String detail, String signals) {
        GradientDrawable bg = new GradientDrawable();
        bg.setCornerRadius(dp(20));
        bg.setColor(getColor(online ? R.color.green_soft : R.color.red_soft));
        bg.setStroke(dp(1), getColor(online ? R.color.green : R.color.red));
        statusPill.setBackground(bg);
        statusPill.setText(online ? "●  ONLINE" : "●  OFFLINE");

        boolean paired = !prefs.getString("admin_token", "").isEmpty();
        statusTitle.setText(online ? "System is working."
                : (paired ? "Cannot reach the relay." : "Pair the app to get signals."));
        statusDetail.setText(detail);

        if (signals == null || signals.trim().isEmpty()) {
            signalList.setText("No signals yet. The engine ships next.");
        } else {
            signalList.setText(signals.trim());
        }
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show();
    }

    private int dp(int v) {
        return (int) (getResources().getDisplayMetrics().density * v);
    }
}
