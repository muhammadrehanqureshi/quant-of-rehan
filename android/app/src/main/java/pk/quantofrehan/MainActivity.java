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
import android.text.SpannableStringBuilder;
import android.text.TextWatcher;
import android.text.style.ForegroundColorSpan;
import android.text.style.TypefaceSpan;
import android.view.View;
import android.view.ViewGroup;
import android.view.animation.AccelerateDecelerateInterpolator;
import android.view.animation.DecelerateInterpolator;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.Spinner;
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
     *      the cadence the moment the relay's answer lands (see scheduleNext;
     *      v2.2.1 makes the foreground cadence the one-second tick at all
     *      times, so the market-state part of this fix is superseded);
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
 * The same order's other two notes: the settings control's ordered offset is     * clamped to the room the screen actually has, which
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
     * One breathing cycle of the status light (owner order 2026-10-13,
     * second note; rebuilt 2026-10-14, seventh note). 2.2 seconds per
     * breath: slow enough to read as alive rather than as a blink, and
     * long enough that a glance never catches it mid flicker. Half of it
     * is one direction of the cycle below, because the animation reverses
     * instead of restarting.
     *
     * Why it is a view animation and not a drawable rewrite: Android has
     * no CSS keyframes, and its equivalent of an accelerated keyframe rule
     * is a view property animation on alpha and scale. The platform keeps
     * those two in the RenderNode and interpolates them on the render
     * thread, so the frames cost this thread nothing.
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
    /** The console's greeting above the QUANT STATUS tile (owner order
     *  2026-10-23). Its sentence flips at noon in Karachi (SO-8). */
    private TextView greeting;
    /** The scanner page's own CUSTOM SCRIPS OF VOL. tile (owner order
     *  2026-10-24, moved off the search page): one dropdown ranked from
     *  the same /prices map the search rows already refresh once per
     *  tick. */
    private View tileVolume;
    /**
     * The search page's own diamond rule (owner order 2026-10-24, second
     * note): the qor_rule include that sits above the SEARCH tile and is
     * drawn from the page state, visible while the search page is and
     * gone on every other page, exactly like the panel it marks.
     */
    private View ruleSearch;
    /** The diamond rule between the search tile and the CUSTOM SCRIPS
     *  OF VOL. tile (owner order 2026-10-24, third pass): the page's own
     *  division, drawn from the scanner page's state beside its tile. */
    private View ruleVolume;
    /**
     * The settings page's THEMES holder (owner order 2026-10-24, third
     * note): the plain container that stands BEHIND the THEMES tile and
     * its own diamond-rule bracket, a sibling of the settings panel and
     * no longer a box inside the settings box. Its visibility is the
     * page's: visible while the settings menu is open, gone everywhere
     * else, exactly like the panel itself.
     */
    private View themesHolder;
    private Spinner volumeSplitSpinner;
    // The dropdown's state arrow (owner order 2026-10-23, 2.0.0):
    // DOWN while the menu is closed (the pull-down cue), UP while it is
    // open (the pull-up cue), declared beside it.
    private ImageView volumeSplitArrow;
    private ImageView themeArrow;
    private ArrayAdapter<String> volumeSplitAdapter;
    /** The one dropdown's chosen menu: 0 = MORE BUYERS & LESS SELLERS,
     *  1 = PRICE MOVING FAST. -1 is "nothing picked yet", so the reveal
     *  stays hidden until he actually chooses (owner order 2026-10-23,
     *  v2.2.1). */
    private int volumeSplitChoice = -1;
    /** The three scrips revealed under the dropdown once a menu is
     *  chosen; the ranking lines print one per row. */
    private TextView volumeReveal;
    /** The settings page's THEMES tile. The spinner's five items and the
     *  selection are theme_name and theme below; the selection survives
     *  between sessions in prefs, so the app opens on the look he chose. */
    private Spinner themeSpinner;
    private TextView appVersion;
    private int themeIndex;
    /**
     * The HUD (owner order 2026-10-22, rebuilt the same day): the thinking
     * orb under the brand, one view that draws the quant's cloud while the
     * console is on screen. It is DRAWN from a boolean the lifecycle owns,
     * exactly the way the settings menu is drawn from `settingsOpen`, so
     * the console is never seen working while it is hidden.
     */
    private ThinkingOrb thinkingOrb;
    /** The HUD's own alive flag, so start and stop have one owner. */
    private boolean hudRunning;
    /** Full relay text retained off-screen; the card renders only execution fields. */
    private String latestSignalBackground = "";
    /**
     * The four pages (owner order 2026-10-23; the scanner joined beside
     * home on 2026-10-24). The selected page's icon is circled in a gold
     * ring on the menu tile at the very bottom; the other three carry
     * only the masked press ripple. The ring and the tint are read from
     * the page booleans here, never from a view's own state, so the
     * paint is idempotent and one-eyed like the rest of the console.
     */
    private ImageView navHome;
    private ImageView navScanner;
    private ImageView navSearch;
    private ImageView navSettings;
    private View settingsPanel;
    private View searchPanel;
    private EditText searchInput;
    private LinearLayout searchResults;
    private TextView searchStatus;
    /** True while the search menu replaces the console, the same law the
     *  settings menu follows: one menu at a time, never two. */
    private boolean searchOpen;
    /**
     * The scanner page (owner order 2026-10-24): the CUSTOM SCRIPS OF
     * VOL. tile's own page, opened by the nav icon beside home. The views
     * are drawn from this boolean exactly the way the search and settings
     * pages are drawn from theirs, and the four states honour the same
     * one-page-at-a-time law.
     */
    private boolean scannerOpen;
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
    /**
     * The HUD's own times (owner order 2026-10-22, rebuilt the same day).
     *
     * The orb's own class owns its every beat; MainActivity only starts
     * and stops it with the console, so the pace constants live beside
     * the frame loop that uses them.
     */

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
        thinkingOrb = (ThinkingOrb) findViewById(R.id.thinking_orb);
        // Owner order 2026-10-23 (v1.9.13): the six feature views were
        // declared but never assigned, so their features silently no-op'd
        // since the pass that built them: the greeting stayed a string id,
        // the THEMES dropdown, the two CUSTOM SCRIPS OF VOL dropdowns, the
        // version line and the volume tile never found themselves. One
        // block assigns them all, which is also their one reminder.
        greeting = (TextView) findViewById(R.id.greeting);
        tileVolume = findViewById(R.id.tile_volume);
        themeSpinner = (Spinner) findViewById(R.id.theme_spinner);
        appVersion = (TextView) findViewById(R.id.app_version);
        volumeSplitSpinner = (Spinner) findViewById(R.id.volume_split_spinner);
        if (volumeSplitSpinner != null) {
            themedInputs.add(volumeSplitSpinner);
        }
        if (themeSpinner != null) {
            themedInputs.add(themeSpinner);
        }
        volumeReveal = (TextView) findViewById(R.id.volume_reveal);
        settingsPanel = findViewById(R.id.settings_panel);
        searchPanel = findViewById(R.id.search_panel);
        ruleSearch = findViewById(R.id.rule_search);
        ruleVolume = findViewById(R.id.rule_volume);
        themesHolder = findViewById(R.id.themes_holder);
        searchInput = findViewById(R.id.search_input);
        searchResults = findViewById(R.id.search_results);
        searchStatus = findViewById(R.id.search_status);

        // The search box: the theme paints it with the same field plate
        // the dropdowns' closed rows wear (v2.2.5 owner order 2026-10-24,
        // fourth note, "the drop down and the search boxes are still
        // purple, make them match the app's current theme").
        themedInputs.add(searchInput);

        // The menu tile at the very bottom (owner order 2026-10-23): the
        // icon of the page he is on is circled, and a tap opens that page.
        // One page at a time is enforced inside the two toggles, so home
        // closes whatever menu is open, and search and settings never
        // share the screen.
        navHome = findViewById(R.id.btn_nav_home);
        navScanner = findViewById(R.id.btn_nav_scanner);
        navSearch = findViewById(R.id.btn_nav_search);
        navSettings = findViewById(R.id.btn_nav_settings);
        // Owner order 2026-10-24: four pages now. Home closes every page
        // that is open, and search, scanner and settings never share the
        // screen: each toggle enforces the one-page law itself.
        navHome.setOnClickListener(v -> {
            setSearchOpen(false);
            setSettingsOpen(false);
            setScannerOpen(false);
        });
        navScanner.setOnClickListener(v -> setScannerOpen(true));
        navSearch.setOnClickListener(v -> setSearchOpen(true));

        // Owner order 2026-10-24, fourth note: the settings icon is its
        // own switch now, the way he tapped it on the screen - one tap
        // opens the page and turns the wheel to the LEFT, untapping it
        // (the same icon again, or home, search or the scanner) closes the
        // page and turns the wheel back to the RIGHT. The boolean is still
        // the one state and setSettingsOpen is still the one writer; the
        // listener just reads it before it lands.
        navSettings.setOnClickListener(v -> setSettingsOpen(!settingsOpen));
        // The selection is painted once at the build too, so the opened
        // console starts with the highlighted icon and not only the
        // ring the XML declared.
        paintNavSelection();
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
        // toggle is one loop over eight references rather than eight calls.
        // findViewById is a tree walk, so doing this here is what keeps the
        // toggle off the layout pass entirely.
        //
        // Owner order 2026-10-22 (v1.9.5): the thinking orb LEAVES the
        // array. The owner ordered the orb on the SEARCH and SETTINGS pages
        // as well, at the same exact placement it holds on the front page,
        // and the panels open BELOW it, exactly where the tiles sat, so a
        // menu no longer takes its space: the orb stays put under the brand
        // and is the one mover on every page of the console.
        consoleViews = new View[]{
                // The greeting is a home-page line, so it hides with the group.
        findViewById(R.id.greeting),
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
        // truth, so a re-entrant tap cannot land on a stale reading. The
        // settings page is opened from the menu tile's own button above;
        // this method stays the one place the state changes.

        findViewById(R.id.btn_open).setOnClickListener(v -> {
            String url = prefs.getString("relay_url", Watcher.DEFAULT_RELAY);
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url + "/health")));
        });

        // Owner order 2026-10-23 (v2.2.1): the ARM THE 1-SECOND WATCH WINDOW
        // button and its alarm loop are gone. The quant already scans every
        // second in the cloud and the relay delivers the feed and the
        // signals from there, so the handset carries no second scanner.

        // Owner order 2026-10-23: the page selects what the app looks like.
        // The spinner is filled with the five pairs in his own order, the
        // remembered selection is applied once in onCreate, and a change at
        // the dropdown repaints the console at once. Nothing here touches
        // the palette behind widgets that carry state of their own: the
        // status badge, the search highlight plates and the rules keep the
        // inks of their own laws.
        themeIndex = prefs.getInt("theme", 0);
        buildThemeSpinner();
        applyTheme(themeIndex);

        buildVolumeSpinners();
        // v2.2.5: the dropdowns' closed rows, their popups and the search
        // box open ON the theme's look, not the app's default, when a
        // non-default theme is remembered.
        applyThemeToInputs(themeIndex);
        wireDropdownArrows();

        writeAppVersion();

        // v1.5.1's battery exemption ask retired with the watch window
        // (v2.2.1): nothing on the handset is scheduled any more, so Doze
        // has nothing to defer and there is nothing to plea for.
        Watcher.kick(this);
    }

    // ----------------------------------------------------------------
    // Owner order 2026-10-23: the menu tile, the themes, the greeting and
    // the volume dropdowns. One block, because they share one law: every
    // state is a field the views are drawn from, never a read of the view
    // tree, so each repaint is idempotent and one call deep.

    /**
     * The selected page is circled (owner order 2026-10-23). The selection
     * is the page state: HOME when no menu is open, otherwise the menu that
     * is. The ring is a background, so it is set rather than negotiated,
     * and the tint follows the ring: brighter while circled.
     *
     * Owner order 2026-10-23 (v2.1.0): the version line is the SETTINGS
     * page's own footer - it keeps the root's last-line station v1.9.14
     * gave it, but a version on every page is now refused: the line shows
     * while the settings menu is open and hides everywhere else. The state
     * is this method's own page truth, so every open and close repaints
     * it and no other place has to remember it.
     */
    private void paintNavSelection() {
        setNavPage(navHome, !searchOpen && !settingsOpen && !scannerOpen);
        setNavPage(navScanner, scannerOpen);
        setNavPage(navSearch, searchOpen);
        setNavPage(navSettings, settingsOpen);
        if (appVersion != null) {
            appVersion.setVisibility(
                    settingsOpen ? View.VISIBLE : View.GONE);
        }
    }

    /**
     * One icon's own face: the filled highlight disc when its page is
     * live, ripple when not.
     *
     * Owner order 2026-10-23 (v2.2.1, "the circle is getting cut off and
     * the entire icon only should be highlighted"): the v2.1.0 answer -
     * a foreground ring plus an 18% size lift - pushed the circle past
     * the icon's own 42dp bounds inside the nav panel, so it read as cut
     * off. There is no size lift and no foreground any more: the whole
     * highlight is one filled translucent gold disc (nav_circle.xml) at
     * exactly the icon's own bounds, the entire icon highlighted, and
     * nothing overflows. Re-set every paint, so a theme or a page change
     * cannot leave one half behind; the ripple stays the unselected face.
     */

    private void setNavPage(ImageView icon, boolean selected) {
        if (icon == null) {
            return;
        }
        icon.setBackgroundResource(selected ? R.drawable.nav_circle : R.drawable.settings_ripple);
        icon.setImageTintList(ColorStateList.valueOf(getColor(
                selected ? R.color.gold_bright : R.color.gold)));
    }

    /**
     * The greeting above the QUANT STATUS tile (owner order 2026-10-23).
     *
     * Owner order 2026-10-24 hardcoded the windows, and they are Karachi's
     * own clock that decides (SO-8), never the handset's zone:
     *
     *     05:01-12:00  "Good morning, Mr. Rehan!"
     *     12:01-17:00  "Good afternoon, sir!"
     *     17:01-19:00  "Good evening, sir!"
     *     19:01-05:00  "You have a wonderful night, Mr. Rehan!"
     *
     * The flat minutes obey the windows as dictated: 05:00, 12:00, 17:00
     * and 19:00 are read as the tail of the window that ENDS there, so
     * 12:00 is still morning, 17:00 still afternoon and 19:00 still
     * evening, and 19:01 to 05:00 inclusive is the night.
     */
    private void refreshGreeting() {
        if (greeting == null) {
            return;
        }
        java.util.Calendar karachi = java.util.Calendar.getInstance(
                java.util.TimeZone.getTimeZone("Asia/Karachi"));
        int hour = karachi.get(java.util.Calendar.HOUR_OF_DAY);
        int minute = karachi.get(java.util.Calendar.MINUTE);
        final int message;
        // The 05:00 flat minute is the NIGHT's own tail, because it ends
        // the night window: the morning starts at 05:01 exactly as the
        // window says, so the first branch peels the boundary minute off
        // before the morning's hour window opens.
        if (hour == 5 && minute == 0) {
            message = R.string.greeting_night;
        } else if (hour >= 5 && hour <= 11
                || (hour == 12 && minute == 0)) {
            message = R.string.greeting_morning;
        } else if (hour >= 12 && hour <= 16
                || (hour == 17 && minute == 0)) {
            message = R.string.greeting_afternoon;
        } else if (hour >= 17 && hour <= 18
                || (hour == 19 && minute == 0)) {
            message = R.string.greeting_evening;
        } else {
            message = R.string.greeting_night;
        }
        greeting.setText(getString(message));
    }

    /**
     * THEMES (owner order 2026-10-23): a dropdown of five pairs, listed in
     * the order he named them. The selection is remembered, so the app
     * opens on the look he chose.
     */
    // The five themes, in the owner's own order; index 0 is the app's
    // current look and needs no repaint beyond identity, so the switch in
    // applyTheme falls through to it.
    private static final int[] THEME_LABELS = {
            R.string.theme_purple, R.string.theme_black, R.string.theme_green,
            R.string.theme_navy, R.string.theme_orange};

    private void buildThemeSpinner() {
        if (themeSpinner == null) {
            return;
        }
        List<String> labels = new ArrayList<>();
        for (int label : THEME_LABELS) {
            labels.add(getString(label));
        }
        ArrayAdapter<String> adapter = styledSpinnerAdapter();
        adapter.addAll(labels);
        themeSpinner.setAdapter(adapter);
        themeSpinner.setSelection(Math.max(0, Math.min(themeIndex,
                THEME_LABELS.length - 1)));
        themeSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> parent,
                                                 View view, int position, long id) {
                if (position != themeIndex) {
                    themeIndex = position;
                    applyTheme(position);
                    // v2.2.5: the dropdowns, their popups and the search
                    // boxes belong to the theme too (owner order
                    // 2026-10-24, fourth note, "drop down menus and the
                    // search boxes are still purple, make them match
                    // the app's current theme").
                    applyThemeToInputs(position);
                }
            }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        });
    }

    /** The input views one theme pass repaints: the two spinners and
     *  the four field boxes, gathered once. */
    private final List<View> themedInputs = new ArrayList<>();

    /**
     * One theme, every input (v2.2.5 owner order above): the closed
     * dropdown rows, their POPUP mosaic and the four field boxes are
     * painted from the theme's own plate, in ONE place. The theme
     * spinner is exempt: as the owner said on 2026-10-24, it already
     * sits inside the plate it is choosing.
     */
    private void applyThemeToInputs(int index) {
        for (View input : themedInputs) {
            if (input == themeSpinner) continue;
            if (input instanceof Spinner) {
                paintDropdown((Spinner) input, index);
            } else {
                paintField(input, index);
            }
        }
    }

    /** One spinner: closed row, popup mosaic, from one plate.
     *  notifyDataSetChanged re-walks every closed row with the code's
     *  current paints; the popup's paint cannot run at a null adapter. */
    private void paintDropdown(Spinner spinner, int index) {
        if (spinner == null) return;
        // The closed row sits inside its tile with the FIELD law's own
        // 12dp corners (the tile plate's 20dp would swallow the field's
        // air), the same plate the boxes wear below.
        spinner.setBackground(fieldPlate(index));
        ArrayAdapter<?> adapter =
                spinner.getAdapter() instanceof ArrayAdapter<?>
                        ? (ArrayAdapter<?>) spinner.getAdapter() : null;
        if (adapter != null) {
            adapter.notifyDataSetChanged();
        }
        // The dropped menu is the STAMP, not the tile paint (the owner's
        // wording "drop down menus ... match the app's current theme", and
        // the v2.2.2 law that a paper never colours a spoon below its
        // station): each theme's own plate id, from this one place.
        int popup = popupResourceFor(index);
        if (popup != View.NO_ID && spinner != themeSpinner) {
            @SuppressWarnings("deprecation")
            android.graphics.drawable.Drawable popupPlate =
                    getResources().getDrawable(popup);
            spinner.setPopupBackgroundDrawable(popupPlate);
        }
    }

    /** One field box: the field's own plate, and the hint ink rides the
     *  theme's heading colour, which is what the boxes' hints were
     *  printed in at v2.2.4. */
    private void paintField(View field, int index) {
        if (field == null) return;
        field.setBackground(fieldPlate(index));
        if (field instanceof TextView) {
            ((TextView) field).setHintTextColor(getColor(
                    hintInkFor(index)));
        }
    }

    /** The tile plate each theme paints (mirrors applyTheme's switch;
     *  one truth, two readers). */
    private int panelResourceFor(int index) {
        switch (index) {
            case 1:  return R.color.theme_black_panel;
            case 2:  return R.color.theme_green_panel;
            case 3:  return R.color.theme_navy_panel;
            case 4:  return R.color.theme_orange_panel;
            default: return R.color.bg_panel;
        }
    }

    /** One rounded field plate per theme, built once and reused: the
     *  field law's own corners, 12dp, on the theme's panel ink (the
     *  plate the closed dropdown row and the search box both wear). */
    private final GradientDrawable[] themeFieldPlates = new GradientDrawable[4];

    private GradientDrawable fieldPlate(int index) {
        if (index <= 0) {
            @SuppressWarnings("deprecation")
            GradientDrawable own = (GradientDrawable) getResources()
                    .getDrawable(R.drawable.field_bg);
            return own;
        }
        GradientDrawable cached = themeFieldPlates[index - 1];
        if (cached == null) {
            cached = new GradientDrawable();
            cached.setColor(getColor(panelResourceFor(index)));
            cached.setCornerRadius(dp(12));
            cached.setStroke(1, getColor(R.color.bg_panel_edge));
            themeFieldPlates[index - 1] = cached;
        }
        return cached;
    }

    /** The POPUP mosaic each theme paints, the stamp hand's own table. */
    private int popupResourceFor(int index) {
        switch (index) {
            case 1:  return R.drawable.dropdown_popup_black;
            case 2:  return R.drawable.dropdown_popup_green;
            case 3:  return R.drawable.dropdown_popup_navy;
            case 4:  return R.drawable.dropdown_popup_orange;
            default: return R.drawable.dropdown_popup;
        }
    }

    /** The hint ink under each theme, the headings' own colour. */
    private int hintInkFor(int index) {
        switch (index) {
            case 1:  return R.color.theme_black_accent;
            case 2:  return R.color.theme_green_accent;
            case 3:  return R.color.theme_navy_accent;
            case 4:  return R.color.theme_orange_accent;
            default: return R.color.text_soft;
        }
    }

    /** The input plate marker: a scrip with a day move at or past this
     *  mark is already capped for the SPEED menu (see the v2.2.5 law
     *  on rankedSpeedSymbols). */
    private static final double CAPPED_MOVE_MARK = 4.9d;
    /**
     * Paint one theme on the console. Each theme is a (cover, panel,
     * heading ink) triple: the scroll root behind everything, the tiles'
     * plates, and the headings' own ink. The purple theme IS the app's
     * declared palette, so its legibility is a property of the app
     * rather than of code, and no other ink CHANGES: the body lines,
     * the search highlight plates, the badge gradients and the diamond
     * rules all keep the inks of their own laws, so a theme can never
     * restyle a state that means something else.
     */
    private void applyTheme(int index) {
        prefs.edit().putInt("theme", index).apply();
        int bg;
        int panel;
        int accent;
        switch (index) {
            case 1:
                bg = R.color.theme_black_bg;
                panel = R.color.theme_black_panel;
                accent = R.color.theme_black_accent;
                break;
            case 2:
                bg = R.color.theme_green_bg;
                panel = R.color.theme_green_panel;
                accent = R.color.theme_green_accent;
                break;
            case 3:
                bg = R.color.theme_navy_bg;
                panel = R.color.theme_navy_panel;
                accent = R.color.theme_navy_accent;
                break;
            case 4:
                bg = R.color.theme_orange_bg;
                panel = R.color.theme_orange_panel;
                accent = R.color.theme_orange_accent;
                break;
            default:
                bg = R.color.bg_deep;
                panel = R.color.bg_panel;
                accent = R.color.gold;
                break;
        }
        int bgColor = getColor(bg);
        View root = findViewById(R.id.scroll_root);
        if (root != null) {
            root.setBackgroundColor(bgColor);
        }
        // Owner order 2026-10-23 (v1.9.13): the repaint used to flatten
        // every tile with setBackgroundColor, which squared the corners the
        // panel drawable owns and killed the plum gradient the owner sent
        // back. The plates keep their round corners on every theme: the
        // purple theme is the app's own rounded gradient (panel_bg) and the
        // other four paint the SAME shape from the theme's own panel ink,
        // cached one rounded drawable per theme and reused.
        View[] plates = {
                findViewById(R.id.tile_status),
                findViewById(R.id.tile_signal),
                findViewById(R.id.tile_market),
                settingsPanel, searchPanel, tileVolume,
                findViewById(R.id.tile_themes),
                findViewById(R.id.nav_tile)};
        for (View plate : plates) {
            if (plate != null) {
                plate.setBackground(themePlate(index, panel));
            }
        }
        int[] headingIds = {
                R.id.brand_title, R.id.status_label, R.id.signal_label,
                R.id.search_heading, R.id.settings_heading,
                R.id.market_heading, R.id.volume_heading,
                R.id.themes_heading};
        for (int id : headingIds) {
            View heading = findViewById(id);
            if (heading instanceof TextView) {
                ((TextView) heading).setTextColor(getColor(accent));
            }
        }
        // v2.3.9: the search rows' plates are the theme's own now, so a
        // theme switch restyles whatever rows are lit this second instead
        // of leaving the previous theme's plates on them until the next
        // keystroke or tick repaints the list.
        if (searchInput != null) {
            renderSearchResults(searchInput.getText().toString());
        }
    }

    /** One rounded plate per theme, built once and reused (v1.9.13). */
    private final GradientDrawable[] themePlates = new GradientDrawable[4];

    /**
     * The plate a theme paints on every tile (owner order 2026-10-23):
     * index 0 is the app's own look, so the plate IS the shipped
     * panel drawable, its corners and gradient intact; the other four
     * draw the same rounded shape in the theme's own panel ink, cached so
     * a theme switch never rebuilds one.
     */
    private GradientDrawable themePlate(int index, int panelColorId) {
        if (index <= 0) {
            @SuppressWarnings("deprecation")
            GradientDrawable own =
                    (GradientDrawable) getResources().getDrawable(
                            R.drawable.panel_bg);
            return own;
        }
        GradientDrawable cached = themePlates[index - 1];
        if (cached == null) {
            cached = new GradientDrawable();
            cached.setColor(getColor(panelColorId));
            cached.setCornerRadius(dp(20));
            cached.setStroke(1, getColor(R.color.bg_panel_edge));
            themePlates[index - 1] = cached;
        }
        return cached;
    }

    /**
     * CUSTOM SCRIPS OF VOL. (owner order 2026-10-23; ONE dropdown since
     * v2.2.1's "make only one drop down menu"): the menu carries both of
     * his entries, MORE BUYERS & LESS SELLERS and PRICE MOVING FAST, in
     * the order he named them, and picking either reveals the three
     * scrips of that ranking. It ranks from the same map the search rows
     * refresh, so the dropdown never costs a request of its own.
     */
    private void buildVolumeSpinners() {
        if (volumeSplitSpinner == null) {
            return;
        }
        volumeSplitAdapter = styledSpinnerAdapter();
        // v2.2.5 (owner order 2026-10-24, fourth note): the scanner's own
        // entry is the menu's FIRST row - the rising prices, capped out -
        // then the two rankings he named before it. The index to ranking
        // mapping lives at paintVolumeReveal alone.
        volumeSplitAdapter.add(getString(R.string.volume_speed_caption));
        volumeSplitAdapter.add(getString(R.string.volume_split_caption));
        volumeSplitSpinner.setAdapter(volumeSplitAdapter);
        volumeSplitSpinner.setOnItemSelectedListener(
                new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> parent, View view,
                                                 int position, long id) {
                // The first callback fires at bind with position 0 and
                // is not a choice of his; only a tap inside the open
                // menu reveals (the Dropdown's own open edges guard it
                // cheaply enough via the -1 sentinel below).
                if (volumeSplitChoice < 0 && !spinnerWasTouched) {
                    spinnerWasTouched = true;
                    return;
                }
                volumeSplitChoice = position;
                paintVolumeReveal();
            }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        });
    }

    /** The dropdown's bind-vs-tap gate for the first onItemSelected. */
    private boolean spinnerWasTouched;

    /**
     * The three dropdowns' own arrows (owner order 2026-10-23, 2.0.0):
     * "when I tell you to have a drop down menu type feature, I want to
     * have the arrow down and up as well to pull up the menu, right now
     * there is none." Each arrow starts DOWN beside its closed menu (the
     * pull-down cue), and the Dropdown's two edges rotate it: UP while the
     * menu is open, DOWN the moment the focus returns and it has closed.
     * Consistency never has to be remembered here precisely because one
     * arrangement and one law serve all three instead of three copies of
     * the work.
     */
    private void wireDropdownArrows() {
        volumeSplitArrow = (ImageView) findViewById(R.id.volume_split_arrow);
        themeArrow = (ImageView) findViewById(R.id.theme_arrow);
        // The layout declares its two dropdowns as pk.quantofrehan.Dropdown
        // (extends Spinner), so the instanceof with the cast below is the
        // one true type and no ClassCastException can enter the wiring.
        if (volumeSplitSpinner instanceof Dropdown) {
            wireDropdownArrow((Dropdown) volumeSplitSpinner,
                    volumeSplitArrow);
        }
        if (themeSpinner instanceof Dropdown) {
            wireDropdownArrow((Dropdown) themeSpinner, themeArrow);
        }
    }

    /** One dropdown's arrow: down while closed, up while open, one flip.
     *
     * The rotation is animated, so the flip is the pull the cue promises.
     * A re-entrant call is free: animate() on an already converged frame
     * re-emits the same values and the view stays where it is.
     */
    private void wireDropdownArrow(Dropdown dropdown, ImageView arrow) {
        if (dropdown == null || arrow == null) {
            return;
        }
        arrow.setRotation(0f);
        dropdown.setOpenListener(open -> arrow.animate()
                .rotation(open ? 180f : 0f)
                .setDuration(150L)
                .start());
    }

    private void renderVolumeSpinners() {
        if (volumeSplitSpinner == null) {
            return;
        }
        paintVolumeReveal();
    }

    /** The reveal (owner order 2026-10-23, v2.2.1): the three scrips of
     *  the chosen menu, one line per scrip. Nothing reveals before he
     *  picks, and a menu with no lines on the feed keeps hiding (SO-3).
     *  A tick that changes no line does not rebuild the text; the search
     *  rows keep their own gate.
     *
     *  v2.3.7 (owner order 2026-10-26, "there is no consistency"): both
     *  menus print ONE sentence now, the leaders card's own shape.
     */
    private void paintVolumeReveal() {
        if (volumeReveal == null) {
            return;
        }
        if (volumeSplitChoice < 0) {
            volumeReveal.setVisibility(View.GONE);
            return;
        }
        java.util.Map<String, Watcher.Quote> quotes = Watcher.quotes();
        // v2.2.5: row 0 is the scanner's riser entry (PRICES RISING FAST),
        // row 1 the busiest B/S ranking (MORE BUYERS & LESS SELLERS). Since
        // v2.3.7 both carry the same sentence: the quantity bracket with
        // the green buy and the red sell, and the money line with the now
        // coloured arrow, so no menu prints a format of its own.
        List<String> ranked = volumeSplitChoice == 1
                ? rankedSplitSymbols(quotes)
                : rankedSpeedSymbols(quotes);
        SpannableStringBuilder styled = volumeRevealText(quotes, ranked);
        if (styled.length() == 0) {
            volumeReveal.setVisibility(View.GONE);
            volumeLines = "";
            return;
        }
        if (styled.toString().equals(volumeLines)) {
            return;
        }
        volumeLines = styled.toString();
        volumeReveal.setText(styled);
        volumeReveal.setVisibility(View.VISIBLE);
    }

    /** The last plain text shown in the reveal, so a tick that changes no
     *  number does not repaint it. */
    private String volumeLines = "";

    /**
     * Menu 1 (owner order 2026-10-23; retitled v2.1.0; re-ranked v2.3.9
     * to the NAME'S OWN law): MORE BUYERS & LESS SELLERS is a fact about
     * which side outweighs the other, so a scrip whose sellers outweigh
     * its buyers is not a row of this menu at all, and the rows rank by
     * the buyers' own SURPLUS (buy minus sell) - never by the combined
     * buy+sell activity, which put a sellers-flooded scrip at the top of
     * the menu (owner report 2026-10-26: MACFL, B=212k against S=9.1M
     * and the price falling 9.72%). A scrip whose frame has no complete
     * range cannot be ranked and is skipped instead of guessed at
     * (SO-3): null is not zero.
     */
    private List<String> rankedSplitSymbols(java.util.Map<String, Watcher.Quote> quotes) {
        List<String> symbols = new ArrayList<>();
        for (java.util.Map.Entry<String, Watcher.Quote> entry : quotes.entrySet()) {
            Watcher.Quote quote = entry.getValue();
            if (quote.buy != null && quote.sell != null) {
                symbols.add(entry.getKey());
            }
        }
        // The label names the dominance: no buyers-majority, no row.
        symbols.removeIf(key -> {
            Watcher.Quote q = quotes.get(key);
            return q.buy <= q.sell;
        });
        symbols.sort((a, b) -> {
            Watcher.Quote qa = quotes.get(a);
            Watcher.Quote qb = quotes.get(b);
            int bySurplus = Long.compare(qb.buy - qb.sell, qa.buy - qa.sell);
            if (bySurplus != 0) {
                return bySurplus;
            }
            return a.compareTo(b);
        });
        return symbols.subList(0, Math.min(symbols.size(), 3));
    }

    /**
     * Menu 2 (owner order 2026-10-23; retitled v2.1.0, "Price moving
     * fast"; v2.2.5 re-scoped by owner order 2026-10-24, fourth note,
     * "don't show me the stocks that are already capped, instead show
     * those stocks whose prices are increasing really fast, for
     * example, during the day that stock was really dead but soon the
     * buyers came in clutch and took the price really high, that is
     * the point of the scanner"). Three rows only, three laws: a
     * falling price does not earn the menu (rising only), a scrip
     * already capped is out (the leaf marks capped as the day's move
     * at the circuit bound), and the move itself is the relay's own
     * day move, unaged (SO-3).
     */
    private List<String> rankedSpeedSymbols(java.util.Map<String, Watcher.Quote> quotes) {
        List<String> symbols = new ArrayList<>();
        for (java.util.Map.Entry<String, Watcher.Quote> entry : quotes.entrySet()) {
            Double move = entry.getValue().changePct;
            if (move == null) {
                continue;                    // no move earned: not ranked (SO-3)
            }
            if (move <= 0d) {
                continue;                    // rising only, owner law.
            }
            if (move >= CAPPED_MOVE_MARK) {
                continue;                    // already capped, owner law.
            }
            symbols.add(entry.getKey());
        }
        symbols.sort((a, b) -> {
            Double moveA = quotes.get(a).changePct;
            Double moveB = quotes.get(b).changePct;
            int bySpeed = Double.compare(moveB, moveA);
            if (bySpeed != 0) {
                return bySpeed;
            }
            return a.compareTo(b);
        });
        return symbols.subList(0, Math.min(symbols.size(), 3));
    }

    /**
     * The three scrips of the chosen menu, in the SAME sentence the
     * leaders card prints (v2.3.7, owner order 2026-10-26, "there is no
     * consistency, no = sign, no , sign, no green and red colors"):
     *
     *   "1. NRSL (B=1,662,818, S=1,762,588 & T=3,425,406)"
     *   "PKR 32.36 ▲ 4.64%"
     *
     * The quantities are the leaders card's own bracket, the plain "="
     * after each letter, the comma after B and the ampersand before T,
     * the buy digits in the brand green and the sell digits in the brand
     * red (2026-10-24's colour law), the total neutral. The money sits on
     * its own line with the arrow, and the arrow plus its percentage take
     * the move's colour and the glyph face, exactly as renderMarket and
     * leadersText print them. A quote without a split still gets its
     * numbered ticker and its money line, never zeros (SO-3). Non-breaking
     * gaps hold each group together, as they hold the leaders card's.
     */
    private SpannableStringBuilder volumeRevealText(
            java.util.Map<String, Watcher.Quote> quotes, List<String> symbols) {
        SpannableStringBuilder sb = new SpannableStringBuilder();
        for (int i = 0; i < symbols.size(); i++) {
            Watcher.Quote quote = quotes.get(symbols.get(i));
            if (quote == null) {
                continue;
            }
            if (sb.length() > 0) {
                sb.append('\n');
            }
            sb.append(String.format(Locale.US, "%d.\u00A0%s",
                    i + 1, symbols.get(i)));
            if (quote.buy != null && quote.sell != null) {
                sb.append("\u00A0(B=");
                colorQuantity(sb, quote.buy, R.color.green);
                sb.append(",\u00A0S=");
                colorQuantity(sb, quote.sell, R.color.red);
                sb.append("\u00A0&\u00A0T=");
                sb.append(String.format(Locale.US, "%,d",
                        quote.buy + quote.sell));
                sb.append(')');
            }
            // The map only ever carries a live price (Watcher's law), so
            // the symbol's presence in the menu is the price's presence on
            // the card; changePct stays boxed, its null a real "no move".
            sb.append('\n');
            sb.append(String.format(Locale.US, "PKR %,.2f", quote.price));
            if (quote.changePct != null) {
                sb.append(' ');
                int from = sb.length();
                sb.append(String.format(Locale.US, "%s %.2f%%",
                        quote.changePct >= 0 ? "\u25B2" : "\u25BC",
                        Math.abs(quote.changePct)));
                sb.setSpan(new ForegroundColorSpan(getColor(
                                quote.changePct >= 0 ? R.color.green : R.color.red)),
                        from, sb.length(), 0);
                sb.setSpan(new TypefaceSpan(ARROW_FACE), from, from + 1, 0);
            }
        }
        return sb;
    }

    /** One coloured quantity: the digits alone carry the colour, the
     *  letters stay neutral, so the ink is the split's own split law. */
    private void colorQuantity(SpannableStringBuilder sb, long value, int res) {
        int from = sb.length();
        sb.append(String.format(Locale.US, "%,d", value));
        sb.setSpan(new ForegroundColorSpan(getColor(res)),
                from, sb.length(), 0);
    }

    /**
     * One drop-down, styled once: every row is the body's one size, the
     * law every non-heading line of the console already holds. The
     * closed row is a body line inside the field box; the dropped rows
     * carry the same ink and a taller padding of their own.
     */
    private ArrayAdapter<String> styledSpinnerAdapter() {
        return new ArrayAdapter<String>(this,
                android.R.layout.simple_spinner_dropdown_item,
                new ArrayList<String>()) {
            @Override
            public View getView(int position, View convertView, ViewGroup parent) {
                TextView row = (TextView) super.getView(position, convertView, parent);
                styleSpinnerRow(row, false);
                return row;
            }

            @Override
            public View getDropDownView(int position, View convertView,
                                        ViewGroup parent) {
                TextView row = (TextView)
                        super.getDropDownView(position, convertView, parent);
                styleSpinnerRow(row, true);
                return row;
            }
        };
    }

    private void styleSpinnerRow(TextView row, boolean dropped) {
        row.setTextSize(13f);
        row.setTextColor(getColor(R.color.text_bright));
        row.setPadding(dp(dropped ? 18 : 10), dp(dropped ? 15 : 6),
                dp(dropped ? 18 : 10), dp(dropped ? 15 : 6));
        row.setText(dropdownLine(row.getText().toString()));
    }

    /**
     * One dropdown line's own inks (owner order 2026-10-23, "drop down
     * menus should also match with the app's UI"): the ticker carries the
     * brand gold the headings carry, the quote keeps the body ink, and a
     * signed day move takes exactly the leader rows' green or red, so an
     * open menu is the console's own face and not the platform's flat
     * grey. A line without the double-space pair (a theme's own label)
     * stays one ink; there is no ticker in it to lift.
     */
    private CharSequence dropdownLine(String line) {
        int split = line.indexOf("  ");
        if (split <= 0) {
            return line;
        }
        SpannableString spans = new SpannableString(line);
        spans.setSpan(new ForegroundColorSpan(getColor(R.color.gold)),
                0, split, SpannableString.SPAN_EXCLUSIVE_EXCLUSIVE);
        String quote = line.substring(split + 2);
        for (int i = quote.length() - 2; i >= 1; i--) {
            char c = quote.charAt(i);
            if ((c == '+' || c == '-') && quote.indexOf('%', i) > 0) {
                spans.setSpan(new ForegroundColorSpan(getColor(
                        c == '+' ? R.color.green : R.color.red)),
                        split + 2 + i, split + 2 + quote.indexOf('%', i) + 1,
                        SpannableString.SPAN_EXCLUSIVE_EXCLUSIVE);
                break;
            }
        }
        return spans;
    }

    /**
     * The version line (owner order 2026-10-23, retitled 2026-10-24):
     * "APP VERSION IS 2.2.5". The prefix resource carries its own
     * trailing space, so the number can never fuse against "IS" (the
     * v2.2.4 defect the sent-back build showed).
     */
    private void writeAppVersion() {
        if (appVersion == null) {
            return;
        }
        String version;
        try {
            version = getPackageManager()
                    .getPackageInfo(getPackageName(), 0).versionName;
        } catch (Exception e) {
            version = "";              // SO-3: never print a version we cannot read
        }
        appVersion.setText(getString(R.string.app_version_prefix) + version);
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
        if (open && scannerOpen) {
            setScannerOpen(false);  // one page at a time (2026-10-24)
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
        // Owner order 2026-10-24, third note: the THEMES tile is its own
        // tile on this page now (its own diamond bracket rides inside the
        // holder) and lives exactly when the panel does: the settings page
        // is the panel PLUS its themes tile, one truth, one toggle.
        if (themesHolder != null) {
            themesHolder.setVisibility(open ? View.VISIBLE : View.GONE);
        }
        // Owner order 2026-10-24, fourth note: the wheel. Opening turns
        // the settings icon to the LEFT (counterclockwise, so a negative
        // rotation); closing turns it back to the RIGHT, home at zero
        // degrees, which is also what it shows while the page is closed.
        // The icon's ring and tint are still paintNavSelection's state;
        // the rotation is this toggle's own and only runs on a change,
        // because the early return above already refused a repeated call.
        if (navSettings != null) {
            navSettings.animate()
                    .rotation(open ? -90f : 0f)
                    .setDuration(280L)
                    .setInterpolator(new DecelerateInterpolator())
                    .start();
        }
        // Owner order 2026-10-23 (v1.9.13), the rule below the settings
        // tile: still GONE. The owner read the tile's own second diamond
        // as an extra one; the THEMES tile now stands behind the panel
        // framed by its own bracket, which is the diamond he asked for on
        // this page (owner order 2026-10-24, third note), and nothing else
        // was added.
        paintNavSelection();
    }

    /**
     * The scanner page (owner order 2026-10-24): the CUSTOM SCRIPS OF VOL.
     * tile's own page, opened by the menu tile's icon beside home. One
     * page at a time, the same law the search and settings toggles
     * enforce: opening the scanner closes whatever page is showing, and
     * every page's close restores the console.
     *
     * The volume tile IS the page: it lives and dies with `scannerOpen`
     * exactly the way it previously lived with the search page (the same
     * v2.2.1 visibility line, moved here), and the pricing tick that
     * restamps it covers both pages alike. Nothing else about the tile
     * moved: its plate, heading, dropdown and reveal are the build's own.
     */
    private void setScannerOpen(boolean open) {
        if (open && searchOpen) {
            setSearchOpen(false);   // one page at a time
        }
        if (open && settingsOpen) {
            setSettingsOpen(false); // one page at a time
        }
        if (open == scannerOpen) {
            return;                 // already there: no animation, no reflow
        }
        scannerOpen = open;
        if (consoleViews != null) {
            // One pass, one state: the console leaves and the tile arrives
            // in the same frame, so no intermediate layout is ever drawn.
            for (View view : consoleViews) {
                view.setVisibility(open ? View.GONE : View.VISIBLE);
            }
        }
        settingsPanel.setVisibility(open ? View.GONE : settingsPanel.getVisibility());
        searchPanel.setVisibility(open ? View.GONE : searchPanel.getVisibility());
        // The search page's own diamond rule above the tile (owner order
        // 2026-10-24, second note) and THEMES tile (third note) follow
        // the pages they belong to: an opening scanner closes the search
        // page and takes its rule and the settings page's themes tile
        // with it; a closing one touches neither, because their pages
        // already own their state.
        if (ruleSearch != null) {
            ruleSearch.setVisibility(open ? View.GONE
                    : ruleSearch.getVisibility());
        }
        if (themesHolder != null) {
            themesHolder.setVisibility(open ? View.GONE
                    : themesHolder.getVisibility());
        }
        if (tileVolume != null) {
            // The CUSTOM SCRIPS OF VOL. tile is the scanner page's own
            // tile (owner order 2026-10-24): it lives and dies with the
            // page, exactly like the menu panels do.
            tileVolume.setVisibility(open ? View.VISIBLE : View.GONE);
        }
        if (ruleVolume != null) {
            // The diamond rule between the search tile and the volume
            // tile (owner order 2026-10-24, third pass) lives exactly
            // when the tile below it does: one truth, both lines.
            ruleVolume.setVisibility(open ? View.VISIBLE : View.GONE);
        }
        paintNavSelection();
        if (open) {
            // The dropdowns ride the /prices read like the search rows
            // do: the page opens onto live data, then stays on the tick.
            refreshPrices();
            renderVolumeSpinners();
        }
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
     * The HUD's cycle, owner order 2026-10-22, rebuilt after the owner sent
     * the reference look that evening: the console's own movers (the diag
     * line's words and the sweeping beam) are RETIRED, and the one mover
     * that remains is the ThinkingOrb under the brand - since owner order
     * 2026-10-22 (third pass) THE SUN, a 3D ball that fills its box and
     * burns every second.
     *
     * The orb runs only while the activity is resumed: startHud is called
     * from onResume and stopHud from onPause, the same law that governs the
     * poll loop and the status beacon (a hidden console holds no animation).
     * Since v1.9.5 the orb is on the SEARCH and SETTINGS pages too, at its
     * exact front-page station, so it is started and stopped once for the
     * whole console and never per page.
     * Owner order 2026-10-23 (v1.9.13) breaks the older law above: the HUD
     * is no longer drawn open or closed alike. The feature stops whenever
     * the market is closed or on a break (see orbGate), so startHud wakes
     * the loop through that gate rather than directly on the view.
     */
    private void startHud() {
        if (hudRunning) {
            return;
        }
        hudRunning = true;
        // The market gate owns the loop's pace from the last known badge:
        // a console that resumes onto a closed market wakes PARKED, and
        // the next render opens or closes the burn from the true state.
        if (thinkingOrb != null) {
            if (orbBurning) {
                thinkingOrb.start();
            } else {
                thinkingOrb.stop();
            }
        }
    }

    /**
     * The orb's market gate (owner order 2026-10-23, v1.9.13): burn only
     * while the badge reads ONLINE, the one boolean the beacon's pulse
     * already trusts, so a closed market, a break or an unreachable relay
     * all park the view, and stop() holding the last frame is the parked
     * picture. `orbBurning` keeps the state between renders so a resume
     * onto a closed market never flashes an open session (SO-3).
     */
    private boolean orbBurning = true;

    private void orbGate(boolean online) {
        orbBurning = online;
        if (thinkingOrb == null || !hudRunning) {
            return;
        }
        if (online) {
            thinkingOrb.start();
        } else {
            thinkingOrb.stop();
        }
    }

    /** Ends the cycle; the orb parks its frame loop and holds its last frame. */
    private void stopHud() {
        hudRunning = false;
        if (thinkingOrb != null) {
            thinkingOrb.stop();
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
        refreshGreeting();
        // Owner order 2026-10-22: the console works only while it is on
        // screen, like every other animation here; onPause ends the cycle
        // and onResume starts it again.
        startHud();
        // Owner order 2026-10-16: the console polls the relay by itself, so
        // nothing on it has to be refreshed by hand. A full round paints the
        // screen on resume (card included), then scheduleNext picks the
        // interval from what the relay last reported. The loop runs only
        // while the activity is resumed (onPause removes it) and only on the
        // main thread's own queue, so a hidden app neither polls nor holds a
        // wake lock, and the watch window in Watcher is untouched by it.
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
        stopHud();
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
     * The interval is ALWAYS Watcher.FAST_POLL_MS, one second, whatever the
     * market is doing: the owner ordered the phone's tick to read like a
     * digital clock, so every number the relay publishes (the INDEX tile's
     * volumes, the leaders, the search rows) lands on the screen the second
     * after the relay has it, open market or not (v2.2.1). Closed sessions
     * cost a request a second only while the console is on screen - onPause
     * still removes the runnable, so an off-screen app schedules nothing.
     * Every path schedules through here, so the cadence is decided in
     * exactly one place and a removeCallbacks on the same runnable makes a
     * re-schedule idempotent instead of stacking a second loop.
     */
    private void scheduleNext() {
        // Owner order 2026-10-23 (v2.2.1, "on the INDEX tile, I am still
        // not seeing the volume moving in real time, like seconds move in
        // a digital clock"): the foreground tick is ALWAYS the one-second
        // cadence now, open market or not, so every number the relay
        // publishes lands on the INDEX tile within a second - the same
        // clock-tick read the search rows already have. The relay only
        // publishes what the feed produced (SO-3): the tile repaints every
        // second and a number moves the second the feed moves, and the
        // phone never invents a digit to keep the clock looking alive.
        cadence.removeCallbacks(tick);
        cadence.postDelayed(tick, Watcher.FAST_POLL_MS);
    }

    /**
     * Refresh the relay's latest market card once per foreground tick.
     *
     * The relay reads its latest published broker snapshot; this request
     * cadence does not make the upstream broker publish faster. A single
     * in-flight guard skips rather than queues work when the network is slow.
     */
    private void pollOnce() {
        // Owner order 2026-10-23: the greeting flips on Karachi's own
        // clock, so the answer is re-decided once per foreground tick;
        // a call that lands just after noon on an already-open screen
        // still greets him by the right sentence.
        refreshGreeting();
        // The search list's prices travel on their own read, once per
        // foreground tick while the panel is open (owner order 2026-10-20,
        // third note: the rows must move every second, like a clock, not
        // once every five). Filtering a keystroke still costs no request;
        // the one in-flight guard skips a tick rather than queueing work.
        // Owner order 2026-10-24: the scanner page's dropdowns tick alike.
        if (searchOpen || scannerOpen) {
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
            // The volume dropdowns ride the same tick (owner order
            // 2026-10-23): one shared read ranks them, and the tick that
            // restamps the rows restamps the dropdowns too. Owner order
            // 2026-10-24: the tile's scanner page is covered alike.
            if (searchOpen || scannerOpen) {
                renderVolumeSpinners();
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
        // Always repaint every foreground tick, every second while the market is live, so the index and the leaders move exactly like the digits on a clock: a frame, even when it is byte-identical to the one before, is what keeps the eye reading motion rather than a paused screen. The live poll already runs on that one-second cadence (scheduleNext), so this is the same loop twice over nothing.
        paint(online, d, s, market);
        // Owner order 2026-10-16 (fourth note): the cadence is re-decided as
        // soon as the relay's answer lands, not at the end of the tick that
        // carried it, and it is re-decided on EVERY answer, painted or not:
        // skipping a repaint must never skip the scheduling point. scheduleNext
        // removes and re-posts the one runnable, so this call cannot stack a
        // second loop.
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

        // Owner order 2026-10-23 (v1.9.13): the AI feature stops animating
        // whenever the market is closed or on a break, ruled by the same ON
        // badge law the beacon's own pulse obeys. The orb's last frame holds
        // still until the session trades again, and one ON answer revives
        // the burn at once.
        orbGate(online);

        if (actualDetail.isEmpty()) {
            statusDetail.setText(getString(R.string.checking));
        } else {
            // Keep the relay's own session detail only; a local UI refresh
            // timestamp is not evidence of broker-data freshness.
            statusDetail.setText(clockSpans(actualDetail));
        }

        if (actualSignals.isEmpty()) {
            signalList.setText(getString(R.string.signal_no_call));
        } else {
            signalList.setText(latestSignalDisplay(actualSignals));
        }
        // The ink follows the sentence that is actually on screen, because a
        // card the tile cannot show (another session's stamp) also lands here
        // as the placeholder (owner order 2026-10-21, 15:35).
        paintSignalInk(signalList.getText().toString());

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
        // Owner order 2026-10-24, third pass ("then I tap on search icon
        // it highlights with the scanner icon highlighted as well"): the
        // v2.2.3 search toggle closed the settings page but never the
        // scanner one, so the scanner stayed open under the search page
        // and its icon kept the highlight two pages at once. One page at
        // a time, the same law every other toggle here keeps: an opening
        // search closes the scanner first, and its own toggle owns the
        // tile and the icon it hands back.
        if (open && scannerOpen) {
            setScannerOpen(false);
        }
        if (consoleViews != null) {
            for (View view : consoleViews) {
                view.setVisibility(open ? View.GONE : View.VISIBLE);
            }
        }
        settingsPanel.setVisibility(open ? View.GONE : settingsPanel.getVisibility());
        searchPanel.setVisibility(open ? View.VISIBLE : View.GONE);
        // Owner order 2026-10-24, second note: the search page's own
        // diamond rule above the tile is drawn from this state. It opens
        // and closes WITH the page: visible while he searches, gone on
        // home and on every other page, the same truth the panel follows.
        if (ruleSearch != null) {
            ruleSearch.setVisibility(open ? View.VISIBLE : View.GONE);
        }
        // Owner order 2026-10-24, third note: the settings page's THEMES
        // tile follows the settings page, so an opening search (which has
        // already closed settings through the toggle above) takes it off
        // the screen; a closing search touches nothing, because both the
        // settings toggle and the scanner's own close paths own their
        // state.
        if (themesHolder != null) {
            themesHolder.setVisibility(open ? View.GONE
                    : themesHolder.getVisibility());
        }
        // The CUSTOM SCRIPS OF VOL. tile left the search page for its own
        // page (owner order 2026-10-24), so this toggle touches only the
        // search panel and its rule now; setScannerOpen owns the tile's
        // visibility.
        paintNavSelection();
        if (open) {
            refreshPrices();
            renderVolumeSpinners();
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
        // v1.8.4 (owner 13:30 report): the rows and the pinned line must be
        // VISIBLE exactly when there is something to show, because the
        // panel's gap law needs the empty views gone but the populated panel
        // needs them seen. A GONE view's margin never opens a gap, and a
        // VISIBLE view shows what arrived.
        searchResults.setVisibility(visible.isEmpty() ? View.GONE : View.VISIBLE);
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
                styleSearchRow(row, symbol, q);
                row.setOnClickListener(v -> selectSymbol(symbol));
                searchResults.addView(row);
                searchRows.put(symbol, row);
            }
            renderedQuery = q;
        } else {
            for (java.util.Map.Entry<String, TextView> entry : searchRows.entrySet()) {
                if (visible.contains(entry.getKey())) {
                    styleSearchRow(entry.getValue(), entry.getKey(), q);
                }
            }
        }
        if (selectedSymbol != null && !visible.contains(selectedSymbol)) {
            selectSymbol(null);
        }
        // The status line is visible only when it has content: an empty
        // view's top margin must never open the bottom gap (v1.8.3), the
        // populated one must be seen (v1.8.4 regression the gap law caused).
        searchStatus.setVisibility(
                searchStatus.getText().length() == 0 ? View.GONE : View.VISIBLE);
        if (selectedSymbol != null) {
            paintSelectedLine();
        } else {
            // Owner order 2026-10-21: neither a no-match nor an empty query
            // prints a sentence under the box any more; the box's own hint
            // and the rows are the whole answer.
            searchStatus.setText("");
        }
    }

    /** Colour one search row from its own live quote and its typed match. */
    private void styleSearchRow(TextView row, String symbol, String q) {
        Watcher.Quote quote = Watcher.quote(symbol);
        if (quote != null) {
            // A move the relay did not report prints no percentage and
            // takes no colour: only a real sign may turn a row green or
            // red (SO-3). A price without a move is neutral ink.
            String tail = quote.changePct == null
                    ? String.format(Locale.US, " PKR %,.2f", quote.price)
                    : String.format(Locale.US, " PKR %,.2f %+.2f%%",
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
        // Owner order 2026-10-21 (15:15): a result row is body text, so it
        // carries the same 13sp as every other non-heading line, the size the
        // signal tile's own sentence uses. Its tracking is its own, a list of
        // tickers rather than a sentence.
        row.setTextSize(13f);
        row.setTextColor(getColor(R.color.text_bright));
        row.setLetterSpacing(0.12f);
        row.setPadding(dp(10), dp(9), dp(10), dp(9));
        // Owner order 2026-10-22 (the search highlight): every row whose
        // symbol STARTS with what is typed lights up while it matches.
        // Typing H lights every H..., typing HU narrows the light, and the
        // moment the last letter of HUBC lands the exact match is lit
        // hardest of the list. v2.3.9 (owner order 2026-10-26: HUBC again
        // orange over the purple theme) returns the highlight to the
        // THEME'S OWN ink: the v2.3.8 gold plates were theme-blind and
        // read orange over the violet field. A matched row wears a lift
        // of the theme's own panel colour - violet on the purple theme,
        // green on the green theme - and the exact match lifts it
        // hardest with a closing hairline in the theme's heading ink.
        // The matched symbol keeps the body's ink; the green/red price
        // tail is the quote's own, set in the spans above, and survives
        // all of this untouched. The highlight is a fact of the QUERY,
        // never of the selection: a row lights because it matches,
        // whether or not it has been tapped.
        if (q == null || q.isEmpty() || !symbol.startsWith(q)) {
            row.setBackground(null);
            return;
        }
        boolean exactMatch = symbol.length() == q.length();
        row.setBackground(highlightPlate(exactMatch));
    }

    /** One highlight plate, v2.3.9: the row lights in a LIFT of the
     *  theme's OWN panel ink, never in an invented wash. The v2.3.8
     *  gold plates were theme-blind: on the purple theme they read
     *  ORANGE over the violet field (the owner's twelfth report today,
     *  HUBC). The panel ink is the colour each theme is NAMED for, so
     *  the purple theme lights violet, the green theme green, and so on;
     *  a prefix match lifts the panel 26% toward white, and the exact
     *  match 42% with a closing hairline in the theme's heading ink, so
     *  the eye reads the exact match hardest while every row stays in
     *  the theme's own family. Built per call, not cached: it is a
     *  keystroke-time path. */
    private GradientDrawable highlightPlate(boolean exact) {
        GradientDrawable plate = new GradientDrawable();
        plate.setCornerRadius(dp(8));
        plate.setColor(lighten(getColor(panelInkFor(themeIndex)),
                exact ? 0.42f : 0.26f));
        if (exact) {
            plate.setStroke(1, getColor(accentInkFor(themeIndex)));
        }
        return plate;
    }

    /** The panel ink each theme is NAMED for (the tile plates' own). */
    private int panelInkFor(int index) {
        switch (index) {
            case 1: return R.color.theme_black_panel;
            case 2: return R.color.theme_green_panel;
            case 3: return R.color.theme_navy_panel;
            case 4: return R.color.theme_orange_panel;
            default: return R.color.bg_panel;
        }
    }

    /** The heading ink each theme is NAMED for: the exact match's
     *  closing hairline follows the headings' own accent. */
    private int accentInkFor(int index) {
        switch (index) {
            case 1: return R.color.theme_black_accent;
            case 2: return R.color.theme_green_accent;
            case 3: return R.color.theme_navy_accent;
            case 4: return R.color.theme_orange_accent;
            default: return R.color.gold;
        }
    }

    /** A lift of one ink toward white, written by hand because the
     *  app compiles against android.jar alone: the arithmetic is the
     *  same blend androidxColorUtils would do, panel + lift * white. */
    private static int lighten(int ink, float lift) {
        int r = (int) (((ink >> 16) & 0xFF)
                + (255 - ((ink >> 16) & 0xFF)) * lift);
        int g = (int) (((ink >> 8) & 0xFF)
                + (255 - ((ink >> 8) & 0xFF)) * lift);
        int b = (int) ((ink & 0xFF) + (255 - (ink & 0xFF)) * lift);
        return 0xFF000000
                | (Math.min(255, r) << 16)
                | (Math.min(255, g) << 8)
                | Math.min(255, b);
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
        // A populated line is always a visible line; the gap law hides only
        // the empty one (v1.8.4, the regression the gap law caused).
        searchStatus.setVisibility(View.VISIBLE);
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
                : String.format(Locale.US, " PKR %,.2f %+.2f%%",
                        quote.price, quote.changePct);
        int from = styled.length();
        styled.append(tail);
        styled.setSpan(new ForegroundColorSpan(getColor(quote.changePct == null
                        ? R.color.text_soft
                        : quote.changePct >= 0 ? R.color.green_hi : R.color.red)),
                from, styled.length(), 0);
        searchStatus.setText(styled);
    }



    /**
     * Owner order 2026-10-21 (15:35): the placeholder is body ink.
     *
     * The tile used to pick its colour from whether the relay had sent a
     * signal at all, so a signal the card could not show (one stamped with
     * another session) reached the screen as "NO SIGNAL AVAILABLE RIGHT NOW"
     * in the bright ink of a real call. The owner read it as white against
     * every other line. The ink now follows the sentence that is actually on
     * screen: the placeholder takes the soft body colour at full alpha, the
     * same as KARACHI and the card's values, and only a real call is bright.
     */
    private void paintSignalInk(String display) {
        boolean noCall = display.contentEquals(getString(R.string.signal_no_call));
        signalList.setTextColor(getColor(noCall
                ? R.color.text_soft : R.color.text_bright));
        signalList.setAlpha(1.0f);
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
     * "Karachi: <clock>" is read in the up-move green.
     *
     * Owner order 2026-10-22: the date and time take the colour the card's
     * own UP percentage rides in (R.color.green), so one shade of green on
     * the console always means "a live number that rose". The brand teal it
     * replaces stays in the palette for the brand lockup's tagline. The
     * face rule of 2026-10-13 stands untouched: the emphasis is colour
     * alone, the LEMON MILK Light line does not move.
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
            sp.setSpan(new ForegroundColorSpan(getColor(R.color.green)),
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
     * double space on the phone. Owner order 2026-10-21 (14:19, CNERGY
     * report): the volume fields separate by ONE space now too, because a
     * five million-share B and a twenty-seven million S wrapped the T onto
     * its own line at the fat separators; one space keeps the whole group on
     * the volume line without dropping a single digit of the feed's counts.
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
                // Owner order 2026-10-21 (14:51): the ticker-to-group gap and
                // the field separators are non-breaking (U+00A0), so a wide
                // row can never wrap mid group.
                // Owner order 2026-10-21 (15:15): the row keeps the body's
                // 13sp. The width comes from the tile, never from the size.
                // Owner order 2026-10-21 (15:35): the three quantities read
                // as a sentence, with a comma after B and an ampersand
                // before T: "(B=..., S=... & T=...)".
                sb.append("\u00A0(B=");
                int buyFrom = sb.length();
                sb.append(String.format(Locale.US, "%,d", row.buy));
                spans.add(new int[]{buyFrom, sb.length(), R.color.green});
                sb.append(",\u00A0S=");
                int sellFrom = sb.length();
                sb.append(String.format(Locale.US, "%,d", row.sell));
                spans.add(new int[]{sellFrom, sb.length(), R.color.red});
                if (row.hasVolume()) {
                    sb.append(String.format(Locale.US, "\u00A0&\u00A0T=%,d)", row.volume));
                } else {
                    // The quantities stand without the exchange's total.
                    sb.append(')');
                }
            } else if (row.hasVolume()) {
                sb.append(String.format(Locale.US, "\u00A0(T=%,d)", row.volume));
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
