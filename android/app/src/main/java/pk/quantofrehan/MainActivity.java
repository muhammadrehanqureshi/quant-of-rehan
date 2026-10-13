package pk.quantofrehan;

import android.animation.ValueAnimator;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.res.ColorStateList;
import android.graphics.drawable.Drawable;
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
 * card, the card's footnote carries the scan cadence sentence instead of the
 * index and ranking wording, and the pinned bottom cadence with the footer
 * rule under it are removed, so the interface ends at the card. Every
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
 * Owner order 2026-10-13 (second note): the settings control stands ON the
 * "Quant of Rehan" baseline rather than centred on its row, a diamond rule
 * divides the system status tile from the latest signal tile, the rule that
 * closed the market card from inside it now stands immediately after that
 * tile's own boundary, and the ONLINE indicator breathes, its opacity and its
 * size, for as long as the relay reports the market OPEN.
 */
public class MainActivity extends Activity {

    /**
     * The face that owns the arrow glyphs.
     *
     * The bundled LEMON MILK faces contain no U+25B2 and no U+25BC (checked
     * against the fonts' own cmaps before they were wired in), so the index
     * line and every money line draw those two characters with the system
     * face. The mark that says a split is an estimate, U+2248, IS present in
     * LEMON MILK, so it needs no override and keeps the brand face.
     */
    private static final String ARROW_FACE = "sans-serif";

    /**
     * The settings icon's quarter turn (owner order 2026-10-13). 220ms reads
     * as one deliberate turn rather than a flicker, and the turn is short
     * enough to finish while the panel is already sliding into place.
     */
    private static final long GEAR_TURN_MS = 220L;

    /**
     * One breathing cycle of the ONLINE indicator (owner order 2026-10-13,
     * second note). 2.2 seconds per breath: slow enough to read as alive
     * rather than as a blink, and long enough that a glance never catches it
     * mid flicker.
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
    private TextView statusPill, statusDetail, signalList;
    private TextView marketIndex, marketLeaders, marketFoot;
    /** Turned and tinted by setSettingsOpen, so it is the ImageView itself. */
    private ImageView btnSettings;
    /** The brand line whose baseline the settings control stands on. */
    private TextView brandTitle;
    private View settingsPanel;
    /** The running ONLINE breathing animation, or null while the dot is still. */
    private ValueAnimator breathAnim;
    /** The exact dot the running animator drives: a re-render installs a new one. */
    private Drawable breathTarget;

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
        brandTitle = findViewById(R.id.brand_title);
        // Owner order 2026-10-13 (second note): the control stands on the
        // brand line's baseline. That line's position comes from Bonskin's
        // metrics and from the system font scale, so it cannot be a fixed
        // margin: it is measured once the title has a layout, and measured
        // again whenever that layout changes.
        brandTitle.addOnLayoutChangeListener(
                (v, left, top, right, bottom, oldLeft, oldTop, oldRight,
                 oldBottom) -> alignSettingsToBrandBaseline());

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
     * Puts the settings control on the brand line's baseline (owner order
     * 2026-10-13, second note).
     *
     * "Aligned with the baseline" is exact here rather than approximate: the
     * control's bottom edge is placed on the same line the title's glyphs sit
     * on, the way an inline glyph would. The offset has to be measured rather
     * than declared, because a 30sp Bonskin line puts its baseline wherever
     * that font's metrics and the system font scale say. The two views are
     * siblings in the header row, so their top and bottom coordinates share
     * one space and the subtraction is direct.
     */
    private void alignSettingsToBrandBaseline() {
        int baseline = brandTitle.getBaseline();     // -1 until the first layout
        if (baseline < 0) {
            return;
        }
        int line = brandTitle.getTop() + baseline;   // in the row's coordinates
        btnSettings.setTranslationY(line - btnSettings.getBottom());
    }

    /**
     * The ONLINE indicator's breathing animation (owner order 2026-10-13,
     * second note).
     *
     * It runs only while the relay reports the market OPEN: that is the one
     * state in which a lit beacon means the quant is working right now. A
     * break, a closed day or an unreported phase leaves the dot still, because
     * a breathing light over a shut market would claim activity there is none
     * (SO-3).
     *
     * The animation is keyframed rather than eased between two ends: 0 to 1 to
     * 0 over BREATH_MS, repeating for as long as the state holds, so every
     * cycle starts and ends at rest and the breath has no seam. The animated
     * value drives both the dot's opacity and its size, and the size is applied
     * to the drawable's own bounds scaled about its centre, so the glow shrinks
     * in place inside the pill instead of sliding.
     */
    private void setStatusBreath(boolean breathe) {
        Drawable dot = statusPill.getCompoundDrawablesRelative()[0];
        if (!breathe || dot == null) {
            stopStatusBreath();
            return;
        }
        if (breathAnim != null && breathAnim.isRunning() && dot == breathTarget) {
            return;                     // this exact dot is already breathing
        }
        stopStatusBreath();             // a re-render hands over a new drawable
        breathTarget = dot;
        breathAnim = ValueAnimator.ofFloat(0f, 1f, 0f);
        breathAnim.setDuration(BREATH_MS);
        breathAnim.setRepeatCount(ValueAnimator.INFINITE);
        breathAnim.setInterpolator(new AccelerateDecelerateInterpolator());
        breathAnim.addUpdateListener(a -> {
            float k = (float) a.getAnimatedValue();
            dot.setAlpha(Math.round(255f
                    * (BREATH_MIN_ALPHA + (1f - BREATH_MIN_ALPHA) * k)));
            float scale = BREATH_MIN_SCALE + (1f - BREATH_MIN_SCALE) * k;
            int halfW = Math.round(dot.getIntrinsicWidth() * scale / 2f);
            int halfH = Math.round(dot.getIntrinsicHeight() * scale / 2f);
            // The centre is read from the live bounds: a re-layout may have
            // just rewritten them, and scaling about the centre never moves
            // it, so the dot cannot drift inside the pill.
            int cx = dot.getBounds().centerX();
            int cy = dot.getBounds().centerY();
            dot.setBounds(cx - halfW, cy - halfH, cx + halfW, cy + halfH);
        });
        breathAnim.start();
    }

    /**
     * Returns the dot to rest: full opacity, its own 18dp size, no animator.
     * Called by every render that is not a live open market, and by onPause.
     */
    private void stopStatusBreath() {
        if (breathAnim != null) {
            breathAnim.cancel();
            breathAnim = null;
        }
        if (breathTarget != null) {
            breathTarget.setAlpha(255);
            int cx = breathTarget.getBounds().centerX();
            int cy = breathTarget.getBounds().centerY();
            int halfW = breathTarget.getIntrinsicWidth() / 2;
            int halfH = breathTarget.getIntrinsicHeight() / 2;
            breathTarget.setBounds(cx - halfW, cy - halfH,
                    cx + halfW, cy + halfH);
            breathTarget = null;
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

        // The breathing light (owner order 2026-10-13, second note): a lit
        // beacon that breathes means the quant is working right now, which is
        // what an OPEN market plus a reachable relay means. A break, a closed
        // day, or a phase the relay did not report leaves the dot still.
        setStatusBreath(online && market != null && "OPEN".equals(market.phase));

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
            marketFoot.setText(footText());
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

        marketFoot.setText(footText());
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
     * approximately" sign: B= and S= are measured from the session's own
     * trade tape, B≈ and S≈ are the relay's estimate from the day's
     * range, which is not order flow (SO-3). The distinction used to live in
     * the card's footnote; the owner replaced that footnote with the scan
     * cadence sentence on 2026-10-12, so the mark moved to where the number
     * is, which is also where it is read.
     *
     * Every field is a boxed Number, so a null means the relay did not report
     * it and the field is skipped rather than printed as a zero.
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
                // "=" for a measured number, U+2248 for an estimated one.
                String mark = row.estimatedSplit() ? "\u2248" : "=";
                // "(" opens at B and ")" closes after T: one bracketed group.
                sb.append(" (B").append(mark);
                int buyFrom = sb.length();
                sb.append(String.format(Locale.US, "%,d", row.buy));
                spans.add(new int[]{buyFrom, sb.length(), R.color.green});
                sb.append("  S").append(mark);
                int sellFrom = sb.length();
                sb.append(String.format(Locale.US, "%,d", row.sell));
                spans.add(new int[]{sellFrom, sb.length(), R.color.red});
                sb.append(String.format(Locale.US, "  T=%,d)", row.volume));
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
        // The arrow ranges last, and only the arrow: the system face draws the
        // two arrow characters, the brand face keeps everything around them.
        for (int[] range : glyphs) {
            sp.setSpan(new TypefaceSpan(ARROW_FACE), range[0], range[1], 0);
        }
        return sp;
    }

    /**
     * The card's footnote.
     *
     * Owner order 2026-10-12: the "Index as of ..." line, the ranking basis
     * and the split wording are all gone, and this slot now carries the scan
     * cadence sentence verbatim. The sentence is read with the volume ranking
     * it describes instead of being pinned below the card, and it is the one
     * place it appears, so the copy still lives in exactly one string
     * resource.
     */
    private String footText() {
        return getString(R.string.scan_cadence);
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show();
    }

    private int dp(int v) {
        return (int) (getResources().getDisplayMetrics().density * v);
    }
}
