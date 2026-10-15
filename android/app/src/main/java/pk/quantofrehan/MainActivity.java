package pk.quantofrehan;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.res.ColorStateList;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.text.SpannableString;
import android.text.style.ForegroundColorSpan;
import android.text.style.TypefaceSpan;
import android.view.View;
import android.view.animation.AccelerateDecelerateInterpolator;
import android.view.animation.DecelerateInterpolator;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
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
 * (drawable/ic_status_online and ic_status_offline), and the volume leaders
 * carry their labelled buy and sell volumes.
 *
 * Owner order 2026-10-12: the "MARKET NOW" label is gone from the market
 * card, the card's footnote took the scan cadence sentence instead of the
 * index and ranking wording, and the pinned bottom cadence with the footer
 * rule under it were removed then, so the interface ended at the card. Every
 * sentence still comes from a string resource, so the copy, the
 * accessibility description and the layout cannot drift.
 *
 * Owner order 2026-10-12 (second note): every volume leader is two lines,
 * the second one carrying the money as "PKR <price>" so a narrow screen can
 * never wrap the label away from the number, the up and down arrows keep a
 * single space before them on the index line and on every leader line, and
 * the card's foot reads "Quant will be scanning the market every 4 minutes
 * when the market is open."
 *
 * Owner order 2026-10-12 (third note): the settings control is a drawn vector
 * gear rather than a text glyph, the market card closes with the same line,
 * diamond, line rule as the two cards above it, the brand and the interface
 * carry the owner's own faces (Bonskin for "Quant of Rehan", LEMON MILK Bold
 * and Light around it), and the double space that sat between a ticker and
 * its buy volume is a single space.
 *
 * Owner order 2026-10-13: the settings control is the owner's own settings.png
 * silhouette, tinted from the palette and on no plate at all, sharing a row
 * with the brand line so it is centred on "Quant of Rehan"; the panel's state
 * is a quarter turn left with a brighter gold, animated back on close. The
 * status tile and the signal tile are drawn in the owner's faces end to end,
 * the "Trading resumes" line is retired from the status tile, and a leader
 * row brackets its volume group.
 *
 * Owner order 2026-10-13 (second note): a diamond rule divides the system
 * status tile from the latest signal tile, and the rule that closed the
 * market card from inside it now stands immediately after that tile's own
 * boundary.
 *
 * Owner order 2026-10-13 (third note): the cadence sentence moves out of the
 * market card to sit immediately after the final diamond rule.
 *
 * Owner order 2026-10-13 (fourth note): the control now stands directly
 * beside the title instead of pinned to the row's far edge. The XML anchors
 * it with layout_toEndOf the title, so the pair holds at any screen width and
 * at any font scale.
 *
 * Owner order 2026-10-13 (fifth note): the cadence sentence sits 12dp below
 * the final diamond rule, the same gap the tiles have below their rules, so
 * the console's last line is on the grid; the two leading newlines are
 * retired from the string resource, whose words are untouched.
 *
 * Owner order 2026-10-14 (sixth note): the settings control is VERTICALLY
 * CENTRED on the "Quant of Rehan" title, so the two read as one line at any
 * font scale. The baseline rule of the second note is retired, and with it
 * the layout listener that measured that baseline after every layout.
 *
 * Owner order 2026-10-14 (seventh note): the breathing light is a view
 * animation now, on the beacon's own alpha and scale, which the platform
 * interpolates on the render thread; the drawable it used to rewrite on a
 * 40ms grid is retired. And only a live market breathes: ONLINE pulses,
 * OFFLINE and CHECKING hold a light that is not moving.
 *
 * Owner order 2026-10-14 (eighth note): the status tile's spacing is one
 * number, @dimen/status_gap, so SYSTEM STATUS to ONLINE and ONLINE to
 * KARACHI are the same air rather than two margins that could drift apart.
 */
public class MainActivity extends Activity {

    /**
     * The face that owns the arrow glyphs and the approximation sign.
     *
     * The bundled LEMON MILK faces contain no U+25B2 and no U+25BC (checked
     * against the fonts' own cmaps before they were wired in), so the index
     * line and every money line draw those two characters with the system
     * face.
     *
     * U+2248 (the mark that says a split is an estimate) IS mapped in LEMON
     * MILK, but the face draws it unusably small at card size: its two bars
     * sit 131 of the font's own 2048 em units apart, so at 13sp they merge
     * into one squiggle and the owner read the result as a tilde (measured
     * 2026-10-15, owner order: resolve it). The sign is therefore drawn by
     * the system face as well, exactly like the arrows, which renders it as
     * the approximation sign it is. The equals sign of a measured count is
     * untouched: LEMON MILK's U+003D is two clean bars 363 units apart.
     */
    private static final String ARROW_FACE = "sans-serif";

    /**
     * The settings icon's quarter turn (owner order 2026-10-13). 220ms reads
     * as one deliberate turn rather than a flicker, and the turn is short
     * enough to finish while the panel is already sliding into place.
     */
    private static final long GEAR_TURN_MS = 220L;

    /**
     * One breathing cycle of the status light (owner order 2026-10-13, second
     * note; rebuilt 2026-10-14, seventh note). 2.2 seconds per breath: slow
     * enough to read as alive rather than as a blink, and long enough that a
     * glance never catches it mid flicker. Half of it is one direction of the
     * cycle below, because the animation reverses instead of restarting.
     *
     * Why it is a view animation and not a drawable rewrite: Android has no
     * CSS keyframes, and its equivalent of an accelerated keyframe rule is a
     * view property animation on alpha and scale. The platform keeps those two
     * in the RenderNode and interpolates them on the render thread, so the
     * frames cost this thread nothing. The retired version wrote the compound
     * drawable's bounds and alpha from an update listener on a 40ms grid,
     * which redrew the whole pill on the UI thread 25 times a second.
     */
    private static final long BREATH_MS = 2200L;

    /**
     * The dim end of the breath, as a fraction of full opacity. It never
     * reaches zero: a status light that vanishes would read as a fault rather
     * than as a pulse.
     */
    private static final float BREATH_MIN_ALPHA = 0.38f;

    /**
     * The small end of the breath, as a fraction of the dot's own 18dp. The
     * dot shrinks and grows in place; its layout box never changes, so the
     * word beside it never moves.
     */
    private static final float BREATH_MIN_SCALE = 0.88f;

    private SharedPreferences prefs;
    /** The state badge: the beacon and the word, one pill. */
    private LinearLayout statusBadge;
    /** The beacon itself, a view so its pulse is an accelerated property. */
    private ImageView statusDot;
    /** The word that, with the colour, carries the state. */
    private TextView statusWord;
    private TextView statusDetail, signalList;
    private TextView marketIndex, marketLeaders;
    /** Turned and tinted by setSettingsOpen, so it is the ImageView itself. */
    private ImageView btnSettings;
    private View settingsPanel;
    /**
     * True while the beacon is breathing, owned by the chain's own halves.
     * Only the state gate reads it, to skip a restart on an already-live
     * chain (owner order 2026-10-15, fourth note): before that the guard sat
     * in startStatusBreath and the chain ended itself after one cycle.
     */
    private boolean breathRunning;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences("qor", MODE_PRIVATE);
        setContentView(R.layout.activity_main);

        statusBadge = findViewById(R.id.status_pill);
        statusDot = findViewById(R.id.status_dot);
        statusWord = findViewById(R.id.status_word);
        statusDetail = findViewById(R.id.status_detail);
        signalList = findViewById(R.id.signal_list);
        marketIndex = findViewById(R.id.market_index);
        marketLeaders = findViewById(R.id.market_leaders);
        settingsPanel = findViewById(R.id.settings_panel);
        btnSettings = findViewById(R.id.btn_settings);

        final EditText tokenBox = findViewById(R.id.token_box);
        tokenBox.setText(prefs.getString("admin_token", ""));

        btnSettings.setOnClickListener(v ->
                setSettingsOpen(settingsPanel.getVisibility() == View.GONE));

        findViewById(R.id.btn_save).setOnClickListener(v -> {
            String t = tokenBox.getText().toString().trim();
            prefs.edit().putString("admin_token", t).apply();
            toast(t.isEmpty() ? "Token cleared." : "Token saved.");
            setSettingsOpen(false);
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
     * The one place the settings state changes (owner order 2026-10-13).
     *
     * Everything "open" means lives here so the three can never drift apart:
     * the panel's visibility, the icon's quarter turn, and its tint. Opening
     * turns the icon 90 degrees to the left (counterclockwise, so a negative
     * rotation); closing animates that rotation back to zero, which is the
     * 90 degree turn to the right the owner asked for. The tint carries the
     * old brand law that the plate's gold ring used to carry, now that the
     * plate itself is gone: gold at rest, brighter gold while the panel is
     * open. A decelerating curve makes the last few degrees settle instead of
     * stopping dead.
     */
    private void setSettingsOpen(boolean open) {
        settingsPanel.setVisibility(open ? View.VISIBLE : View.GONE);
        btnSettings.animate()
                .rotation(open ? -90f : 0f)
                .setDuration(GEAR_TURN_MS)
                .setInterpolator(new DecelerateInterpolator())
                .start();
        btnSettings.setImageTintList(ColorStateList.valueOf(getColor(
                open ? R.color.gold_bright : R.color.gold)));
    }

    /**
     * The status light's pulse (owner order 2026-10-14, seventh note).
     *
     * Only a live market breathes. The badge is ONLINE exactly when the relay
     * is reachable and the session is trading, so the pulse belongs to that
     * state alone: OFFLINE (a closed market, its break, or an unreachable
     * relay) and CHECKING (the app has not heard from the relay yet) hold a
     * light that is not moving. The state is still carried by the word and
     * the colour, never by the motion, so a pulse cannot claim the market is
     * trading (SO-3).
     *
     * Two accelerated view properties carry it: alpha and scale on the
     * beacon's own view. The platform keeps those in the RenderNode and
     * interpolates them on the render thread, which is this platform's
     * equivalent of a CSS keyframe animation on transform and opacity: the
     * frames touch no layout, no measure and no draw on this thread. Each
     * direction is half a cycle and the return is the same curve mirrored,
     * so one breath is BREATH_MS and the light never jumps.
     *
     * Owner order 2026-10-15 (fourth note): the breath NEVER stalls while
     * the console is on an ONLINE console. Measured live on 2026-10-15, the
     * first build breathed exactly once and then froze: the return half
     * ended by calling startStatusBreath again, and that method's own
     * "already breathing" guard saw breathRunning still true and silently
     * ended the chain. The guard has therefore moved to the state gate
     * (breathIfOnline), which is the only caller that must not restart a
     * live chain, and startStatusBreath is now the pure "begin the next
     * full cycle" step the chain calls back into: the loop owns its own
     * continuation, so one breath follows the next without a gap and
     * without a restart for as long as the market is ON.
     */
    private void startStatusBreath() {
        if (statusDot == null) {
            return;                     // nothing to pulse
        }
        breathRunning = true;
        breatheTo(BREATH_MIN_ALPHA, BREATH_MIN_SCALE, this::breatheBack);
    }

    /**
     * Starts the pulse only for a live market (owner order 2026-10-14).
     * Every other state, and every hidden console, is still. The gate also
     * owns the "already breathing" check (owner order 2026-10-15, fourth
     * note): a re-render on an ONLINE console must not restart a chain that
     * is already alive, but it must never be the thing that ends one
     * either, which was the freeze the owner measured.
     */
    private void breathIfOnline(boolean online) {
        if (online) {
            if (!breathRunning) {
                startStatusBreath();
            }
        } else {
            stopStatusBreath();
        }
    }

    /** One direction of the breath, and the next step when it lands. */
    private void breatheTo(float alpha, float scale, Runnable next) {
        statusDot.animate()
                .alpha(alpha)
                .scaleX(scale)
                .scaleY(scale)
                .setDuration(BREATH_MS / 2)
                .setInterpolator(new AccelerateDecelerateInterpolator())
                .withEndAction(next)
                .start();
    }

    /**
     * The return: full opacity and the beacon's own 18dp again. Its end
     * action calls startStatusBreath, which is the NEXT full cycle: with the
     * already-alive guard moved to breathIfOnline (owner order 2026-10-15,
     * fourth note), the two halves now chain forever until the state flips,
     * instead of the first return silently ending everything.
     */
    private void breatheBack() {
        if (!breathRunning) {
            return;                     // stopped while this half was queued
        }
        breatheTo(1f, 1f, this::startStatusBreath);
    }

    /**
     * Returns the beacon to rest: full opacity, its own 18dp size, no
     * animation. Called for every state that is not a live market, and by
     * onPause.
     */
    private void stopStatusBreath() {
        breathRunning = false;
        if (statusDot != null) {
            statusDot.animate().cancel();
            statusDot.setAlpha(1f);
            statusDot.setScaleX(1f);
            statusDot.setScaleY(1f);
        }
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

    @Override
    protected void onPause() {
        super.onPause();
        // A hidden console holds no animation: the breath stops with the view,
        // and onResume's refresh starts it again.
        stopStatusBreath();
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
        statusBadge.setBackground(bg);
        // The owner's marker law, 2026-10-11: one status light beside the
        // word, lit for ONLINE and hollow for OFFLINE, so the badge reads as
        // an indicator rather than as an emoji. A shut session is OFFLINE.
        // The beacon is its own view since 2026-10-14, which is what lets the
        // pulse below be a view property animation.
        statusDot.setImageResource(online
                ? R.drawable.ic_status_online : R.drawable.ic_status_offline);
        statusWord.setText(getString(online
                ? R.string.status_online : R.string.status_offline));
        statusWord.setTextColor(getColor(online
                ? R.color.green : R.color.red));
        // Material accessibility: the badge is a live state indicator, so it
        // announces itself and carries a spoken description, and its two
        // children are decoration for the reader: the word alone would be
        // read a second time against that description. A glyph alone reads
        // as "multiplication X" to a screen reader.
        statusBadge.setContentDescription(getString(online
                ? R.string.cd_status_online : R.string.cd_status_offline));

        // The status light's pulse (owner order 2026-10-14, seventh note):
        // only a live market breathes, so the beacon is still while the market
        // is closed, while it is on its midday break, and while the relay is
        // unreachable. The word and the colour carry the state; the motion
        // never does, so a pulse cannot claim the market is trading (SO-3).
        breathIfOnline(online);

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

    /**
     * "Karachi: <clock>" keeps the brand teal.
     *
     * Owner order 2026-10-13: the tile is drawn in the owner's face end to
     * end, so the monospace family and the synthesised bold that used to force
     * the clock into a legacy face are retired. The colour emphasis stays,
     * because it marks the one live value on the line without touching the
     * type.
     */
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
            sp.setSpan(new ForegroundColorSpan(getColor(R.color.teal_bright)),
                    start, end, 0);
        }
        return sp;
    }

    /** The third card: index points and the day's volume leaders. */
    private void renderMarket(Watcher.Market market) {
        if (market == null) {
            marketIndex.setText(getString(R.string.market_waiting));
            marketLeaders.setText(getString(R.string.market_leaders_waiting));
            return;
        }

        if (market.hasIndex()) {
            // hasIndex() guarantees all three are non-null, so the unboxing
            // below cannot throw. A half-reported index renders as waiting
            // instead of as a zero.
            String line = String.format(Locale.US, "KSE100  %,.2f %s %,.2f (%.2f%%)",
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
                // One character only: the arrow, never the number after it.
                sp.setSpan(new TypefaceSpan(ARROW_FACE), from, from + 1, 0);
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
    }

    /**
     * Every leader is two lines (owner order 2026-10-12):
     *   "1. ABC (B=12,345  S=9,876  T=22,221)"
     *   "PKR 12.52 \u25B2 1.05%"
     *
     * The gap between the ticker and the volume group is ONE space (owner
     * order 2026-10-12, third note): it used to be three, which read as a
     * double space on the phone. The two spaces that separate the volume
     * fields stay, because they are what groups B, S and T apart.
     *
     * Owner order 2026-10-13: the group is bracketed, "(" opening at the B
     * indicator and ")" closing after the exchange's total, so the three
     * fields read as one block instead of trailing off the ticker. A row with
     * no split opens the bracket at the total it does have, so the shape of
     * the line never changes between rows.
     *
     * The price never shares a line with the volumes any more: the second
     * line is the money line, with the currency label welded to the number so
     * a narrow screen can never wrap between them. The arrow keeps a single
     * space before it on this line and on the index line.
     *
     * The buy and sell volumes are the owner's request of 2026-10-10, now
     * always shown for the top three when the relay reports them: buying is
     * green, selling is red, the total stays neutral, so the two sides read
     * apart before the digits do.
     *
     * What the numbers MEAN is marked on the number itself, with the "is
     * approximately" sign: B= and S= are the session's own trade tape's
     * counts, B≈ and S≈ are the relay's estimate from the day's range,
     * which is not order flow (SO-3). The distinction used to live in
     * the card's footnote, which carried the scan cadence sentence from
     * 2026-10-12 until that sentence moved below the final rule on 2026-10-13.
     * The mark lives on the number instead, which is where it is read.
     *
     * Owner order 2026-10-15: the buy and sell quantities are the exact, raw
     * numbers the feed produced, and they carry the "=" a measured count
     * deserves whether the tape covered the whole day or the part of it it
     * saw. The approximation sign is drawn by the system face (see
     * ARROW_FACE): LEMON MILK's own U+2248 collapses into a tilde at this
     * size, which is what the quantity fields were showing. The operator is
     * the same character in both marks; only the face changes.
     *
     * Every field is a boxed Number, so a null means the relay did not report
     * it and the field is skipped rather than printed as a zero. A row that
     * has a split but no total keeps its bracket and its two sides: the
     * quantities are the point of the group.
     */
    private SpannableString leadersText(List<Watcher.Leader> leaders) {
        StringBuilder sb = new StringBuilder();
        List<int[]> spans = new ArrayList<>();   // {from, to, colour resource}
        List<int[]> glyphs = new ArrayList<>();  // {from, to} system-face ranges
        for (int i = 0; i < leaders.size(); i++) {
            Watcher.Leader row = leaders.get(i);
            if (i > 0) {
                sb.append('\n');
            }
            sb.append(String.format(Locale.US, "%d. %s", i + 1, row.symbol));
            if (row.hasSplit()) {
                // "=" for the tape's own counted feeds, U+2248 for the
                // day's-range estimate (drawn by ARROW_FACE, never by the
                // brand face: see the class comment on that constant).
                boolean estimated = row.estimatedSplit();
                String mark = estimated ? "\u2248" : "=";
                // "(" opens at B and ")" closes after T: one bracketed group.
                sb.append(" (B").append(mark);
                int buyFrom = sb.length();
                sb.append(String.format(Locale.US, "%,d", row.buy));
                spans.add(new int[]{buyFrom, sb.length(), R.color.green});
                if (estimated) {
                    glyphs.add(new int[]{buyFrom - 1, buyFrom});
                }
                sb.append("  S").append(mark);
                int sellFrom = sb.length();
                sb.append(String.format(Locale.US, "%,d", row.sell));
                spans.add(new int[]{sellFrom, sb.length(), R.color.red});
                if (estimated) {
                    glyphs.add(new int[]{sellFrom - 1, sellFrom});
                }
                if (row.hasVolume()) {
                    sb.append(String.format(Locale.US, "  T=%,d)", row.volume));
                } else {
                    // The quantities stand without the exchange's total.
                    sb.append(')');
                }
            } else if (row.hasVolume()) {
                sb.append(String.format(Locale.US, " (T=%,d)", row.volume));
            }
            // The money line: opened whenever there is a price or a move to
            // show, so even a price-less row puts its change on its own line
            // instead of hanging it off the volumes.
            if (row.price != null || row.changePct != null) {
                sb.append('\n');
            }
            if (row.price != null) {
                sb.append(String.format(Locale.US, "PKR %,.2f", row.price));
            }
            if (row.changePct != null) {
                if (row.price != null) {
                    sb.append(' ');
                }
                int from = sb.length();
                sb.append(String.format(Locale.US, "%s %.2f%%",
                        row.changePct >= 0 ? "\u25B2" : "\u25BC",
                        Math.abs(row.changePct)));
                spans.add(new int[]{from, sb.length(), row.changePct >= 0
                        ? R.color.green : R.color.red});
                glyphs.add(new int[]{from, from + 1});
            }
        }
        SpannableString sp = new SpannableString(sb.toString());
        for (int[] span : spans) {
            sp.setSpan(new ForegroundColorSpan(getColor(span[2])),
                    span[0], span[1], 0);
        }
        // The glyph ranges last, and only the glyphs: the system face draws
        // the two arrow characters and, on an estimated row, the two
        // approximation signs; the brand face keeps everything around them.
        for (int[] range : glyphs) {
            sp.setSpan(new TypefaceSpan(ARROW_FACE), range[0], range[1], 0);
        }
        return sp;
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show();
    }

    private int dp(int v) {
        return (int) (getResources().getDisplayMetrics().density * v);
    }
}
