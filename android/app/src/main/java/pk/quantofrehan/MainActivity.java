package pk.quantofrehan;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.res.ColorStateList;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.text.Editable;
import android.text.SpannableString;
import android.text.TextWatcher;
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
 * Owner order 2026-10-16 (v1.7.1): that sentence's interval tracks the real
 * one, which was the cloud cadence of that order (config.SCAN_INTERVAL_SECONDS)
 * rather than the retired 4 minute local tick. The console also repaints at
 * that cadence for as long as it is on screen instead of once per open. The
 * interval became one second on 2026-10-19 (see the v1.7.7 note below).
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
 *
 * Owner order 2026-10-16 (fourth note of the day): the console was reported as
 * never refreshing every second. Three causes, all in this file's neighbours,
 * and all three are fixed here:
 *
 *   1. the interval was chosen BEFORE the first answer arrived. onResume
 *      scheduled the next round from marketOpenSeen, which is false on a
 *      fresh process, so an open market was polled at the 30 second idle
 *      interval until a whole idle round had completed. render now re-decides
 *      the cadence the moment the relay's answer lands (see scheduleNext);
 *   2. the relay's own clock ("Karachi: <date> HH:MM PKT", cloud/worker.js
 *      hhmm) has MINUTE resolution, so a perfect one second poll redrew an
 *      identical screen for up to 60 seconds and looked like no poll at all.
 *      The status tile therefore also carries the app's own contact line, to
 *      the second (see liveLine), which is the phone's record of its own last
 *      answer and is labelled as such rather than as a market fact (SO-3);
 *   3. the header and the settings hint both described a 30 second repaint.
 *      The sentence the owner was reading is the SCAN cadence (the cloud
 *      scanner ran every 30 seconds under SO-13 at that time) and stayed
 *      byte-identical, but the hint now states the two cadences apart, so the
 *      panel could not read as a promise that the screen updates every 30
 *      seconds. On 2026-10-19 the scan itself moved to one second, so the two
 *      cadences now agree.
 *
 * The same order's other two notes: the settings control's ordered offset is
 * clamped to the room the screen actually has (see applySettingsShift), which
 * is what stopped its press gradient being sliced, and the OFFLINE light is
 * the ONLINE light in red and still (drawable/ic_status_offline).
 *
 * Owner order 2026-10-19 (v1.7.7), the dashboard pass: the OFFLINE tile is a
 * dark red gradient instead of a pale tint; the latest signal tile shows the
 * ticker and the three execution prices and nothing else, through SignalText;
 * the settings tile carries no token field and no relay jargon; the KSE100
 * line has no "feed unconfirmed" sentence, only the broker's own clock; and
 * the strategy scan moved from 30 seconds to the one second cadence, which
 * this console already polls at while the relay reports a live session.
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
    /** Full relay text retained off-screen; the card renders only execution fields. */
    private String latestSignalBackground = "";
    /** Turned and tinted by setSettingsOpen, so it is the ImageView itself. */
    private ImageView btnSettings;
    private View settingsPanel;
    /** The search control beside the gear (owner order 2026-10-20). */
    private ImageView btnSearch;
    private View searchPanel;
    private EditText searchInput;
    private LinearLayout searchResults;
    private TextView searchStatus;
    /** True while the search menu replaces the console, the same law the
     *  settings menu follows: one menu at a time, never two. */
    private boolean searchOpen;
    /** One price refresh is in flight at a time, on every foreground tick
     *  while the search is open (owner order 2026-10-20, third note). */
    private boolean pricesInFlight;
    /** The symbol the owner tapped in the search list, until he clears it.
     *  Owner report 2026-10-20: the tapped stock vanished when the next
     *  second's price refresh redrew the list, so the selection now survives
     *  the tick that follows it. */
    private String selectedSymbol;
    /** The rows currently on screen, keyed by symbol, so the per-second
     *  refresh restyles them in place instead of rebuilding the list and
     *  making it visibly blink out on every tick. */
    private final java.util.Map<String, TextView> searchRows =
            new java.util.LinkedHashMap<>();
    /** The query the visible rows were built for, so a tick that changes no
     *  number does not change the rows. */
    private String renderedQuery = "";
    /** The pinned symbol's latest B/S answer, so the selection line survives
     *  every price tick. Cleared when the selection is. */
    private CharSequence selectedBase = "";
    /**
     * The session date the relay last reported, in Karachi (SO-8).
     *
     * The EDGE owns the clock, exactly as it owns market_open: the phone asks
     * the relay what day it is rather than deciding from its own zone, so a
     * handset set to another country cannot promote an old call to today's.
     * Empty until the first answer, and an empty date never suppresses a card.
     */
    private String relayDate = "";
    /**
     * The console's own views, hidden together while the settings menu is
     * open: the three tiles, the three rules between them and the cadence
     * sentence. Built once in onCreate, so the toggle is one loop over an
     * array and never a re-inflation of the layout.
     */
    private View[] consoleViews;
    /**
     * The settings state. The views are drawn from this boolean; no code ever
     * reads a view's visibility back to decide what the state is, which is
     * what makes the toggle idempotent and loop free.
     */
    private boolean settingsOpen;
    /**
     * True while a relay round is in flight (owner order 2026-10-16).
     *
     * A one second poll on a slow connection could otherwise start a round
     * before the last one answered, which queues requests, keeps old answers
     * arriving out of order and burns battery re-rendering the same data.
     * One round at a time is the whole guard.
     */
    private boolean liveInFlight;
    /**
     * True while the console is on screen.
     *
     * A round started just before the console is hidden can answer just after
     * it, and rendering it then would restart the status breath that onPause
     * deliberately stopped, leaving an animation running for a view nobody can
     * see. The callback therefore always releases the in-flight flag and only
     * paints when the console is resumed, which keeps the older promise that a
     * hidden console holds no animation and no poll.
     */
    private boolean resumed;
    /**
     * The relay's own market state, which sets the poll interval (SO-8).
     *
     * The phone never decides from its own clock whether the market is open:
     * the last answer from the relay carries `market_open`, and that value
     * alone chooses between the one second live poll and the slow idle poll.
     */
    private boolean marketOpenSeen;
    /**
     * True while the beacon is breathing, owned by the chain's own halves.
     * Only the state gate reads it, to skip a restart on an already-live
     * chain (owner order 2026-10-15, fourth note): before that the guard sat
     * in startStatusBreath and the chain ended itself after one cycle.
     */
    private boolean breathRunning;
    /**
     * Skips a repaint when the relay's answer has not changed (v1.7.5).
     *
     * The console polls once a second on a live market, while the relay's own
     * clock has minute resolution and its card moves only when the cloud
     * capture publishes. Most answers are therefore identical, and painting
     * one costs a measure, a layout and a draw of three tiles to show the same
     * pixels. The gate is plain Java so its decision is exercised on the JVM
     * (tests/test_android_render_gate.py) rather than only read.
     */
    private final RenderGate renderGate = new RenderGate();
    /** The two badge backgrounds, built once instead of once per answer. */
    private GradientDrawable badgeOnline;
    private GradientDrawable badgeOffline;

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
        btnSearch = findViewById(R.id.btn_search);
        searchPanel = findViewById(R.id.search_panel);
        searchInput = findViewById(R.id.search_input);
        searchResults = findViewById(R.id.search_results);
        searchStatus = findViewById(R.id.search_status);
        btnSearch.setOnClickListener(v -> setSearchOpen(!searchOpen));
        // Instant search (owner order 2026-10-20): every keystroke filters
        // the symbol list the relay's own snapshot carries, so the list is
        // local and a letter costs no request.
        searchInput.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence t, int a, int b, int c) { }
            @Override public void onTextChanged(CharSequence t, int a, int b, int c) { }
            @Override public void afterTextChanged(Editable e) {
                renderSearchResults(e == null ? "" : e.toString());
            }
        });

        // Owner order 2026-10-16: the console's tiles, the rules between them
        // and the cadence sentence, gathered ONCE so the exclusive-settings
        // toggle is one loop over seven references rather than seven calls.
        // findViewById is a tree walk, so doing this here is what keeps the
        // toggle off the layout pass entirely.
        consoleViews = new View[]{
                findViewById(R.id.tile_status),
                findViewById(R.id.rule_status_signal),
                findViewById(R.id.tile_signal),
                findViewById(R.id.rule_after_signal),
                findViewById(R.id.tile_market),
                findViewById(R.id.rule_after_market),
                findViewById(R.id.scan_cadence)};

        // Owner order 2026-10-19: the settings tile carries no technical
        // clutter, so there is no token field and no save button. The relay
        // serves the latest signal as a public read and its write routes stay
        // admin gated, which is why the phone needs no credential at all.
        //
        // The tap reads the STATE, never a view's visibility: one source of
        // truth, so a re-entrant tap cannot land on a stale reading.
        btnSettings.setOnClickListener(v -> setSettingsOpen(!settingsOpen));

        findViewById(R.id.btn_open).setOnClickListener(v -> {
            String url = prefs.getString("relay_url", Watcher.DEFAULT_RELAY);
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url + "/health")));
        });

        findViewById(R.id.btn_arm).setOnClickListener(v -> {
            Watcher.armAlarms(this);
            maybeRequestBatteryExemption(true);
            toast("Watchdog armed. Refreshing every 5 minutes.");
        });

        // The ordered icon offset, applied as far as the screen can show it
        // (owner order 2026-10-16, fourth note: the press gradient was being
        // cut off). Posted so it runs after the first layout pass, which is
        // the first moment the control and the window have real geometry.
        applySettingsShift();

        Watcher.kick(this);
        // v1.5.1: ask once, quietly, so Doze and OEM battery managers do not
        // defer the watchdog. The Arm button can always ask again on demand.
        maybeRequestBatteryExemption(false);
    }

    /**
     * The settings control's offset, bounded by the screen it is drawn on.
     *
     * The owner's orders stack to a translation of @dimen/settings_shift_x to
     * the right and @dimen/settings_shift_y upward, and that is exactly what
     * this applies whenever the screen has the room. On a narrow phone it may
     * not: the control hangs off the brand title, the title is centred, and a
     * 30sp Bonskin line is about 200dp wide, so on a 320dp or 360dp content
     * area the ordered 44.1dp pushes the control's box past the window's right
     * edge. Its pixels there are not clipped by a parent, they simply do not
     * exist, which is what the owner saw as a cut off gradient.
     *
     * So the translation is clamped to the number of pixels actually available
     * between the control's own right edge and the window's, and never to a
     * guessed width: a wide phone gets the ordered offset in full, a narrow
     * one loses only the pixels it does not have, and the press flash is whole
     * either way. The vertical offset needs no clamp: every ancestor of the
     * header now draws outside its own bounds (see activity_main.xml), and the
     * 6.3dp a 42dp box overhangs its row is inside the screen.
     */
    private void applySettingsShift() {
        btnSettings.post(() -> {
            View window = findViewById(android.R.id.content);
            if (window == null || window.getWidth() == 0) {
                return;                     // no geometry yet: the XML offset stands
            }
            float orderedX = getResources().getDimension(R.dimen.settings_shift_x);
            float orderedY = getResources().getDimension(R.dimen.settings_shift_y);
            int[] windowAt = new int[2];
            int[] gearAt = new int[2];
            window.getLocationOnScreen(windowAt);
            btnSettings.getLocationOnScreen(gearAt);
            // Where the box's right edge sits with the shift REMOVED, so the
            // room is a measurement rather than a re-derivation of the anchor.
            int naturalRight = (int) (gearAt[0] - btnSettings.getTranslationX())
                    + btnSettings.getWidth();
            int room = windowAt[0] + window.getWidth() - naturalRight;
            btnSettings.setTranslationX(Math.min(orderedX, Math.max(0f, room)));
            btnSettings.setTranslationY(orderedY);
        });
    }

    /**
     * The one place the settings state changes (owner orders 2026-10-13 and
     * 2026-10-16), and the one place the view toggle is decided.
     *
     * Everything "open" means lives here so nothing can drift apart:
     * the console's visibility, the panel's visibility, the icon's quarter
     * turn, and its tint. The state is the field `settingsOpen`; the views are
     * DRAWN from it, never asked. That direction is what keeps the toggle free
     * of re-render loops: a listener reads one boolean, sets it once, and the
     * method returns early when the value has not changed, so a repeated tap,
     * a restored activity or a stray second call cannot re-run the animations
     * or thrash the view tree.
     *
     * Owner order 2026-10-16: while the panel is open the view shows the
     * settings menu EXCLUSIVELY. The console's three tiles (system status,
     * latest signal, the market card), the three rules between and after them
     * and the cadence sentence are all set to GONE together, from the array
     * built once in onCreate. GONE rather than INVISIBLE on purpose: the menu
     * then takes the space the console gave up instead of leaving a hole the
     * owner would have to scroll past, and a hidden view is out of the
     * accessibility tree, so a screen reader announces the menu alone.
     *
     * Opening turns the icon 90 degrees to the left (counterclockwise, so a
     * negative rotation); closing animates that rotation back to zero, which
     * is the 90 degree turn to the right the owner asked for. The tint
     * carries the old brand law that the plate's gold ring used to carry, now
     * that the plate itself is gone: gold at rest, brighter gold while the
     * panel is open. A decelerating curve makes the last few degrees settle
     * instead of stopping dead.
     */
    private void setSettingsOpen(boolean open) {
        if (open && searchOpen) {
            setSearchOpen(false);   // one menu at a time
        }
        if (open == settingsOpen) {
            return;                     // already there: no animation, no reflow
        }
        settingsOpen = open;
        if (consoleViews != null) {
            // One pass, one state: the console leaves and the menu arrives
            // in the same frame, so no intermediate layout is ever drawn.
            for (View view : consoleViews) {
                view.setVisibility(open ? View.GONE : View.VISIBLE);
            }
        }
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
        resumed = true;
        // onPause stopped the breath, so the first answer after a resume must
        // paint even when it equals the one the console last showed: that
        // paint is what starts the breath again on a live market.
        renderGate.reset();
        refresh();
        // Owner order 2026-10-16: the console polls the relay by itself, so
        // nothing on it has to be refreshed by hand. A full round paints the
        // screen on resume (card included), then scheduleNext picks the
        // interval from what the relay last reported. The loop runs only
        // while the activity is resumed (onPause removes it) and only on the
        // main thread's own queue, so a hidden app neither polls nor holds a
        // wake lock, and the watchdog in Watcher is untouched by it.
        scheduleNext();
    }

    @Override
    protected void onPause() {
        super.onPause();
        // A hidden console holds no animation and no poll: the breath stops
        // with the view and the cadence loop is removed, and onResume starts
        // both again. The resumed flag also silences a round already in
        // flight when this ran, so its answer cannot restart the breath.
        resumed = false;
        cadence.removeCallbacks(tick);
        stopStatusBreath();
    }

    /** The foreground refresh loop. */
    private final android.os.Handler cadence =
            new android.os.Handler(android.os.Looper.getMainLooper());
    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            pollOnce();
            scheduleNext();
        }
    };

    /**
     * The one scheduling point of the whole loop (owner order 2026-10-16).
     *
     * The interval is a function of the relay's own answer, so it changes the
     * moment the market does: a live session is polled every
     * Watcher.FAST_POLL_MS (one second), which is as fast as a new signal can
     * appear, and a closed market, its midday break or an unreachable relay
     * falls back to Watcher.REFRESH_MS (thirty seconds), because nothing on
     * the screen can change until the session does and a shut market must not
     * cost a request a second on the owner's battery. Every path schedules
     * through here, so the cadence is decided in exactly one place and a
     * removeCallbacks on the same runnable makes a re-schedule idempotent
     * instead of stacking a second loop.
     */
    private void scheduleNext() {
        cadence.removeCallbacks(tick);
        cadence.postDelayed(tick, marketOpenSeen
                ? Watcher.FAST_POLL_MS : Watcher.REFRESH_MS);
    }

    /**
     * Refresh the relay's latest market card once per foreground tick.
     *
     * The relay reads its latest published broker snapshot; this request
     * cadence does not make the upstream broker publish faster. A single
     * in-flight guard skips rather than queues work when the network is slow.
     */
    private void pollOnce() {
        // The search list's prices travel on their own read, once per
        // foreground tick while the panel is open (owner order 2026-10-20,
        // third note: the rows must move every second, like a clock, not
        // once every five). Filtering a keystroke still costs no request;
        // the one in-flight guard skips a tick rather than queueing work.
        if (searchOpen) {
            refreshPrices();
        }
        if (!liveInFlight) {
            refreshLive();
        }
    }

    /** Refresh the compact symbol price map the search rows colour from. */
    private void refreshPrices() {
        if (pricesInFlight) {
            return;
        }
        pricesInFlight = true;
        Watcher.fetchPrices(this, () -> runOnUiThread(() -> {
            pricesInFlight = false;
            if (isFinishing() || isDestroyed()) {
                return;
            }
            if (searchOpen && searchInput != null) {
                renderSearchResults(searchInput.getText().toString());
            }
        }));
    }

    /**
     * A full display refresh, including the market card.
     * Used on resume and after the token is saved.
     */
    private void refresh() {
        liveInFlight = true;
        Watcher.fetchStatus(this, (online, reachable, detail, signals, market) ->
                runOnUiThread(() -> {
                    liveInFlight = false;
                    // A round that outlived its activity paints nothing and
                    // releases its reference at once: without this the lambda
                    // would hold a finished console for one more frame.
                    if (isFinishing() || isDestroyed()) {
                        return;
                    }
                    if (resumed) {
                        render(online, detail, signals, market);
                    }
                }));
    }

    /**
     * The one-second foreground round: health, signals and latest card.
     *
     * The card route is read from the relay's latest pushed broker snapshot.
     * It may be unchanged between upstream publications, which the UI labels
     * with the source timestamp rather than presenting the poll as a new tick.
     */
    private void refreshLive() {
        liveInFlight = true;
        Watcher.fetchLive(this, (online, reachable, detail, signals, market) ->
                runOnUiThread(() -> {
                    liveInFlight = false;
                    if (isFinishing() || isDestroyed()) {
                        return;
                    }
                    if (resumed) {
                        render(online, detail, signals, market);
                    }
                }));
    }

    private void render(boolean online, String detail, String signals,
                        Watcher.Market market) {
        String d = detail == null ? "" : detail.trim();
        String s = signals == null ? "" : signals.trim();
        latestSignalBackground = s;
        // The relay's own date, not the handset's: the card's session is
        // compared against the EDGE's clock, the same authority that owns
        // market_open (owner order 2026-10-20).
        if (market != null && market.date != null && !market.date.isEmpty()) {
            relayDate = market.date;
        }
        // One decision per answer (v1.7.5): an answer that matches the one
        // already on screen is not painted again. The gate compares the ANSWER,
        // never a view, so a skipped paint cannot leave the screen and the
        // state disagreeing. See RenderGate.
        if (renderGate.changed(online, d, s, marketFingerprint(market))) {
            paint(online, d, s, market);
        }
        // Owner order 2026-10-16 (fourth note): the cadence is re-decided as
        // soon as the relay's answer lands, not at the end of the tick that
        // carried it, and it is re-decided on EVERY answer, painted or not:
        // skipping a repaint must never skip the scheduling point. scheduleNext
        // removes and re-posts the one runnable, so this call cannot stack a
        // second loop.
        marketOpenSeen = online;
        scheduleNext();
    }

    /**
     * Draw one relay answer. Only the gate's caller can reach this, so it is
     * always news: the badge, the beacon, the two sentences and the card.
     */
    private void paint(boolean online, String actualDetail, String actualSignals,
                       Watcher.Market market) {
        statusBadge.setBackground(badge(online));
        // The owner's marker law, 2026-10-11: one status light beside the
        // word, lit for ONLINE and hollow for OFFLINE, so the badge reads as
        // an indicator rather than as an emoji. A shut session is OFFLINE.
        // The beacon is its own view since 2026-10-14, which is what lets the
        // pulse below be a view property animation.
        statusDot.setImageResource(online
                ? R.drawable.ic_status_online : R.drawable.ic_status_offline);
        statusWord.setText(getString(online
                ? R.string.status_online : R.string.status_offline));
        // Owner order 2026-10-19: the OFFLINE tile is a dark red gradient, so
        // the word switches to the on-dark ink. White on #6B1616 is about
        // 10:1, far past the 4.5:1 that body text needs, and the word and the
        // beacon still carry the state without relying on colour alone.
        statusWord.setTextColor(getColor(online
                ? R.color.on_green : R.color.on_red));
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

        if (actualDetail.isEmpty()) {
            statusDetail.setText(getString(R.string.checking));
        } else {
            // Keep the relay's own session detail only; a local UI refresh
            // timestamp is not evidence of broker-data freshness.
            statusDetail.setText(clockSpans(actualDetail));
        }

        if (actualSignals.isEmpty()) {
            signalList.setText(getString(R.string.signal_no_call));
            signalList.setTextColor(getColor(R.color.text_soft));
            signalList.setAlpha(0.65f);
        } else {
            signalList.setText(latestSignalDisplay(actualSignals));
            signalList.setTextColor(getColor(R.color.text_bright));
            signalList.setAlpha(1.0f);
        }

        if (market != null) {
            // Every live display round carries the current relay snapshot;
            // its source timestamp keeps unchanged feed data honest.
            renderMarket(market);
        }
    }

    /**
     * The badge background for a state, built once and reused.
     *
     * It used to be a fresh GradientDrawable on every answer, so a one second
     * poll allocated a drawable a second and re-ran the stroke resolution for
     * it. Two states exist, so two drawables exist.
     */
    private GradientDrawable badge(boolean online) {
        GradientDrawable cached = online ? badgeOnline : badgeOffline;
        if (cached != null) {
            return cached;
        }
        GradientDrawable bg = new GradientDrawable();
        bg.setCornerRadius(dp(18));
        if (online) {
            // Owner order 2026-10-20: ONLINE is the OFFLINE tile's own
            // gradient in the brand green, top to bottom, closed by a
            // hairline, so the two states differ by hue and nothing else.
            bg.setOrientation(GradientDrawable.Orientation.TOP_BOTTOM);
            bg.setColors(new int[]{getColor(R.color.green_deep),
                    getColor(R.color.green_deep_edge)});
            bg.setStroke(dp(1), getColor(R.color.green_deep_line));
            badgeOnline = bg;
        } else {
            // Owner order 2026-10-19: OFFLINE reads as a dark, prominent red
            // rather than a pale tint. The gradient runs top to bottom, dark
            // enough at both ends to carry white text.
            bg.setOrientation(GradientDrawable.Orientation.TOP_BOTTOM);
            bg.setColors(new int[]{getColor(R.color.red_deep),
                    getColor(R.color.red_deep_edge)});
            bg.setStroke(dp(1), getColor(R.color.red_deep_line));
            badgeOffline = bg;
        }
        return bg;
    }

    /**
     * A cheap summary of everything the market card draws.
     *
     * The gate needs one number per answer, and it must move exactly when the
     * card would: the session status and its stamp, the index and its two
     * movements, the basis lines, the note, and every leader's symbol, price,
     * movement and volumes. A field the card shows and this does not fold in
     * would be a change the screen never receives, so the fold lists them one
     * by one rather than hashing an object's identity.
     */
    private static int marketFingerprint(Watcher.Market market) {
        if (market == null) {
            return 0;
        }
        int h = market.answered ? 1 : 0;
        h = 31 * h + (market.feedStatusFresh ? 1 : 0);
        h = 31 * h + (market.feedHalted ? 1 : 0);
        h = 31 * h + text(market.feedStatus);
        h = 31 * h + text(market.feedStatusRaw);
        h = 31 * h + text(market.feedStatusAsOf);
        h = 31 * h + text(market.basis);
        h = 31 * h + text(market.note);
        h = 31 * h + number(market.indexValue);
        h = 31 * h + number(market.indexChange);
        h = 31 * h + number(market.indexPct);
        h = 31 * h + text(market.indexAsOf);
        for (Watcher.Leader leader : market.leaders) {
            h = 31 * h + text(leader.symbol);
            h = 31 * h + number(leader.price);
            h = 31 * h + number(leader.changePct);
            h = 31 * h + count(leader.volume);
            h = 31 * h + count(leader.buy);
            h = 31 * h + count(leader.sell);
            h = 31 * h + text(leader.splitMethod);
        }
        return h;
    }

    private static int text(String value) {
        return value == null ? 0 : value.hashCode();
    }

    private static int number(Double value) {
        return value == null ? 0 : Double.valueOf(value).hashCode();
    }

    private static int count(Long value) {
        return value == null ? 0 : Long.valueOf(value).hashCode();
    }

    /**
     * The tile's primary signal data, and nothing else (owner order
     * 2026-10-19).
     *
     * The relay carries a full text card: a "QoR intraday <date>" header, the
     * session's rule paragraphs, and on a no-trade day a note explaining why
     * nothing was taken. Those are the workings, not the signal, so the tile
     * renders the ticker and three execution numbers and nothing else, and
     * collapses every other state to one word. The parsing lives in
     * SignalText (plain Java, no Android imports) so tests/test_android_signal_text.py
     * runs it on the JVM against the shapes the relay actually serves.
     */
    /**
     * The search menu (owner order 2026-10-20): the console leaves, the field
     * arrives, and the list under it filters on every keystroke, Google style.
     * A prefix query only, because a KMIALL script is what the owner types:
     * "F" lists every symbol that starts with F, "FF" narrows to FFC and FFL.
     */
    private void setSearchOpen(boolean open) {
        if (open == searchOpen) {
            return;
        }
        searchOpen = open;
        if (open && settingsOpen) {
            setSettingsOpen(false);
        }
        if (consoleViews != null) {
            for (View view : consoleViews) {
                view.setVisibility(open ? View.GONE : View.VISIBLE);
            }
        }
        settingsPanel.setVisibility(open ? View.GONE : settingsPanel.getVisibility());
        searchPanel.setVisibility(open ? View.VISIBLE : View.GONE);
        btnSearch.setImageTintList(ColorStateList.valueOf(getColor(
                open ? R.color.gold_bright : R.color.gold)));
        if (open) {
            refreshPrices();
            searchInput.setText("");
            searchInput.requestFocus();
            renderSearchResults("");
        } else {
            // Closed search owns its state: the pinned symbol and its rows go
            // with the panel, so a reopened search starts clean.
            searchInput.clearFocus();
            selectedSymbol = null;
            selectedBase = "";
            searchRows.clear();
            renderedQuery = "";
        }
    }

    /** Filter the relay's symbol list by prefix and draw up to eight rows. */
    private void renderSearchResults(String query) {
        if (searchResults == null || searchStatus == null) {
            return;
        }
        List<String> symbols = Watcher.symbols();
        String q = query == null ? "" : query.trim().toUpperCase(Locale.US);
        // The rows carry a state (a tapped symbol stays pinned), so they are
        // only rebuilt when the query or the visible set actually changes; a
        // price tick restyles the SAME views in place. Owner report 2026-10-20:
        // the tapped stock used to vanish the second after the tap, because
        // every tick tore the whole list down and drew it again.
        if (symbols.isEmpty()) {
            searchRows.clear();
            renderedQuery = q;
            selectSymbol(null);
            searchStatus.setText(getString(R.string.search_waiting));
            return;
        }
        List<String> filtered = new java.util.ArrayList<>();
        for (String symbol : symbols) {
            if (symbol.startsWith(q)) {
                filtered.add(symbol);
            }
        }
        if (q.isEmpty()) {
            filtered.clear();
        }
        List<String> visible = filtered.subList(0, Math.min(filtered.size(), 8));
        boolean rebuild = !q.equals(renderedQuery)
                || !visible.equals(new java.util.ArrayList<>(searchRows.keySet()));
        if (rebuild) {
            searchResults.removeAllViews();
            searchRows.clear();
            // Owner order 2026-10-20 (second note): every result carries the
            // stock's own price and percentage, both in the colour of its move,
            // so the list answers "which one" before a tap does. A symbol with
            // no fresh quote is listed bare rather than with a guessed number.
            for (String symbol : visible) {
                TextView row = new TextView(this);
                styleSearchRow(row, symbol);
                row.setOnClickListener(v -> selectSymbol(symbol));
                searchResults.addView(row);
                searchRows.put(symbol, row);
            }
            renderedQuery = q;
        } else {
            for (java.util.Map.Entry<String, TextView> entry : searchRows.entrySet()) {
                if (visible.contains(entry.getKey())) {
                    styleSearchRow(entry.getValue(), entry.getKey());
                }
            }
        }
        if (selectedSymbol != null && !visible.contains(selectedSymbol)) {
            selectSymbol(null);
        }
        if (selectedSymbol != null) {
            paintSelectedLine();
        } else {
            // Owner order 2026-10-21: neither a no-match nor an empty query
            // prints a sentence under the box any more; the box's own hint
            // and the rows are the whole answer.
            searchStatus.setText("");
        }
    }

    /** Colour one search row from its own live quote, or list a symbol bare. */
    private void styleSearchRow(TextView row, String symbol) {
        Watcher.Quote quote = Watcher.quote(symbol);
        if (quote != null) {
            // A move the relay did not report prints no percentage and
            // takes no colour: only a real sign may turn a row green or
            // red (SO-3). A price without a move is neutral ink.
            String tail = quote.changePct == null
                    ? String.format(Locale.US, " PKR %,.2f", quote.price)
                    : String.format(Locale.US, " PKR %,.2f  %+.2f%%",
                            quote.price, quote.changePct);
            SpannableString styled = new SpannableString(symbol + tail);
            styled.setSpan(new ForegroundColorSpan(getColor(quote.changePct == null
                            ? R.color.text_soft
                            : quote.changePct >= 0 ? R.color.green_hi : R.color.red)),
                    symbol.length(), styled.length(), 0);
            row.setText(styled);
        } else {
            row.setText(symbol);
        }
        row.setTextSize(15f);
        row.setTextColor(getColor(R.color.text_bright));
        row.setLetterSpacing(0.12f);
        row.setPadding(dp(10), dp(9), dp(10), dp(9));
    }

    /** One symbol's B, S and T, asked of the relay's own split law. */
    private void selectSymbol(String symbol) {
        selectedSymbol = symbol;
        if (symbol == null) {
            // Clearing always discards the pinned symbol's stale detail line
            // with it, so a restored view can never print B/S of another
            // stock.
            selectedBase = "";
            return;
        }
        searchStatus.setText(getString(R.string.search_loading));
        Watcher.fetchStock(this, symbol, (ok, line) -> runOnUiThread(() -> {
            if (isFinishing() || isDestroyed()) {
                return;
            }
            if (!symbol.equals(selectedSymbol)) {
                return;
            }
            // The relay's own B/S detail for the pinned symbol, kept so a
            // refresh can never swap the line back to the empty hint. The
            // tail under it is restamped from the live quote every tick
            // (owner report 2026-10-20).
            selectedBase = ok
                    ? line : getText(R.string.search_unavailable);
            paintSelectedLine();
        }));
    }



    /** The pinned symbol's own line, restamped from its own live quote.
     *
     * Owner order 2026-10-21: the fetched base is a spannable that keeps
     * the green B and the red S from the fetch, so the live tail is
     * appended to it rather than rebuilding the line from plain text,
     * which would have dropped both colours on every tick.
     */
    private void paintSelectedLine() {
        if (selectedSymbol == null || searchStatus == null) {
            return;
        }
        Watcher.Quote quote = Watcher.quote(selectedSymbol);
        if (quote == null) {
            // No fresh quote yet: the fetched detail stands alone, never a
            // guessed price (SO-3).
            if (selectedBase != null && selectedBase.length() > 0) {
                searchStatus.setText(selectedBase);
            }
            return;
        }
        android.text.SpannableStringBuilder styled =
                new android.text.SpannableStringBuilder(
                        selectedBase == null ? "" : selectedBase);
        String tail = quote.changePct == null
                ? String.format(Locale.US, " PKR %,.2f", quote.price)
                : String.format(Locale.US, " PKR %,.2f  %+.2f%%",
                        quote.price, quote.changePct);
        int from = styled.length();
        styled.append(tail);
        styled.setSpan(new ForegroundColorSpan(getColor(quote.changePct == null
                        ? R.color.text_soft
                        : quote.changePct >= 0 ? R.color.green_hi : R.color.red)),
                from, styled.length(), 0);
        searchStatus.setText(styled);
    }



    private String latestSignalDisplay(String raw) {
        // Owner order 2026-10-20: a card stamped with another session is
        // not today's call. Before this, a Tuesday screen still showed
        // Friday's HCAR row because the tile rendered whatever the relay
        // last carried and never asked what day it was.
        String stamp = SignalText.cardDate(raw);
        if (!stamp.isEmpty() && !relayDate.isEmpty() && !stamp.equals(relayDate)) {
            return getString(R.string.signal_no_call);
        }
        String text = SignalText.compact(raw);
        // The two states are words, not numbers, so they come from resources:
        // one place for the copy and one place for the accessible sentence.
        if (SignalText.NO_TRADE.equals(text)) {
            return getString(R.string.signal_none);
        }
        if (SignalText.UNAVAILABLE.equals(text)) {
            return getString(R.string.signal_unavailable);
        }
        return text;
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
            // Owner order 2026-10-20 (second note): the clock that used to sit
            // after the percentage is gone. The line is the index and its
            // move; when a reader needs the stamp, the relay's own health and
            // the status line still carry it.
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
     * Owner order 2026-10-20 (third note): the quantities carry the plain
     * "=" and nothing follows the closing bracket. The EST tag and the
     * approximation mark that preceded it are both retired from the phone,
     * because the owner read them as part of the quantity. The relay still
     * labels how each pair was produced in its own split_source, so the
     * weaker number is never passed off as order flow where the data lives
     * (SO-3); the card shows the digits the feed produced.
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
                // Owner order 2026-10-20 (second note): both sides carry the
                // plain "=", and the EST tag after the total is gone. The
                // numbers are the numbers; the split's method is stated in
                // the relay's own source line, not as a suffix on the tile.
                // "(" opens at B and ")" closes after T: one bracketed group.
                sb.append(" (B=");
                int buyFrom = sb.length();
                sb.append(String.format(Locale.US, "%,d", row.buy));
                spans.add(new int[]{buyFrom, sb.length(), R.color.green});
                sb.append("  S=");
                int sellFrom = sb.length();
                sb.append(String.format(Locale.US, "%,d", row.sell));
                spans.add(new int[]{sellFrom, sb.length(), R.color.red});
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
        // the two arrow characters, and the brand face keeps everything
        // around them. Since 2026-10-20 the quantities carry no mark of their
        // own, and no tag follows the group.
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
