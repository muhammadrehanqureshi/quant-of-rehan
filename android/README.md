# android/ : Quant of Rehan companion app

A small, logo-branded Android app for the owner's phone. It answers two
questions at a glance: is the quant working, and what are the latest
signals. Signal-only by construction (SO-1): the app talks only to the
Cloudflare relay, never to Telegram, never to a broker.

## What it shows

- A live status card: ONLINE when a session is live AND the relay answers,
  with the relay's Karachi clock (v1.3.0 dropped the next-event line by
  owner order). Outside the session, and on weekends and PSX holidays, the
  pill shows OFFLINE with a red cross: a closed market is never reported as
  ONLINE (owner order 2026-10-09).
- The pill follows the relay's `market_state` phase and carries a drawn
  status light beside the word (vector drawables, v1.6.0) with a spoken
  accessibility description, so a screen reader never reads a bare
  "multiplication X" and the state never depends on a font. Since v1.6.9 that
  light breathes only while the market is live: ONLINE pulses, and OFFLINE
  (a closed market, its midday break, an unreachable relay) and CHECKING hold
  a still light, because a pulse over a shut market would claim activity
  there is none (owner orders 2026-10-13 third note and 2026-10-14 seventh
  note). The pulse itself is a view property animation on the beacon's own
  alpha and scale, which the platform interpolates on the render thread, so
  the console never redraws a badge to make it breathe.
- Owner order 2026-10-10 retired "PSX session closed". The exchange's midday
  break now reads "Market is on a break right now" and every other shut state
  reads "Market is closed right now.", in each case the relay's own sentence
  (the "(trading resumes 14:32 PKT)" tail was retired on 2026-10-13, see the
  v1.6.5 note below). A phase the relay
  did not report reads "Market status not reported by the relay yet." rather
  than guessing a session, because a wrong "closed" on a live session is the
  worst thing this card can say. The app never derives a session from its own
  clock, which is what keeps a phone, the PC and the edge in agreement.
- Financial values are boxed and nullable rather than sentinel encoded, so
  "the relay did not report this" is explicit and the compiler forces every
  read site to handle it. A NaN or an infinity from the feed becomes unknown
  instead of reaching the card. The relay body is read with a 512 KB cap so a
  data spike empties the card instead of crashing the app.
- A signals panel fed by the relay's `/signals` feed. Since v1.7.6 that read
  is public and the phone holds no credential; the write route stays admin
  gated.
- The market card, third box (v1.5.0, extended in v1.6.0, v1.6.2 and v1.6.3): the
  KSE100 index with its points and percentage, then the three KMIALL stocks
  with the highest current session volume, each with its day's percentage
  change (green up, red down) and its volume. The relay builds it from the
  PSX Data Portal's own pages and caches it for five minutes. Since v1.7.6
  the leader prices and the KSE100 line are overlaid from the live broker
  snapshot the relay's Durable Object holds (`/quotes`), so those numbers move
  with the feed while the card's ranking still comes from the cached build;
  only a fresh broker row may replace a value. Since v1.6.7 the console closes with the cadence
  sentence under the last diamond rule - 12dp below it since v1.6.8, the same
  gap the tiles use (owner orders 2026-10-13, third and fifth notes) -
  instead of carrying it inside the card.
- v1.6.2, owner order 2026-10-12: the card carries no "MARKET NOW" label any
  more, the old "Index as of ..." footnote is gone, and the pinned bottom
  cadence with the footer rule under it are removed, so the interface ends at
  the card. The card's own foot carries the cadence sentence (string resource
  `scan_cadence`, re-worded in v1.6.3 below). The 4 is the real interval,
  `config.TICK_INTERVAL_MINUTES`.
- v1.6.3, owner order 2026-10-12: every volume leader is two lines. The first
  line is the rank, the symbol and the volumes; the second is the money line,
  "PKR 12.52" followed by the day's change, so the currency label and the
  price can never wrap apart on a narrow screen. The up and down arrows keep a
  single space before them on the index line and on every leader line. The
  card's foot now reads "Quant will be scanning the market every 4 minutes
  when the market is open." (The sentence later moved below the final rule
  and its interval has tracked the scan since; v1.7.7 reads "every second".)
- v1.6.3 volume rows read
  `1. CNERGY (B=12,345  S=9,876  T=22,221)` on the first line and
  `PKR 12.52 up 1.05%` on the second, where B and S are the session's buy and
  sell volumes and T is the exchange's own total. v1.6.4 turned the three
  spaces between the ticker and its buy volume into one: the owner saw that
  gap as a double space. The two spaces that separate B, S and T stay, because
  they are what groups the three fields apart. v1.6.5 brackets that group: the
  "(" opens at B and the ")" closes after T, so the three fields read as one
  block rather than trailing off the ticker.
- v1.6.4, owner order 2026-10-12 (third note): the settings control is a drawn
  vector gear on a masked ripple instead of the U+2699 text glyph (the glyph
  is retired, along with its string resource, and the button now carries a
  short spoken name instead of the whole help paragraph, until v1.6.5
  replaced the drawn gear with the owner's own settings.png image); the market card
  closes with the same line, diamond, line rule as the header and the signal
  card, so all three tiles end the same way; the interface is set in the
  owner's own faces, Bonskin for the brand and LEMON MILK Bold and Light
  around it. See "Type" below for what each face can and cannot draw.
  Version 1.6.4, versionCode 18.
  B and S come from the broker's real-time tape (`src/data/tick_volume.py`,
  split into the card's numbers by `src/data/volume_split.py`): the venue's
  own running session total is divided into windows, and each window's shares
  are attributed by where the prints traded (at the ask means a buyer, at the
  bid means a seller) or by the tick rule. The mark on the number says which
  answer it is: `B=` is measured when the tape covered the day, `B≈` is an
  estimate, either the tape's own flow projected onto the day's total or, when
  the tape has no usable coverage, the position of the day's range. The
  exchange publishes no side, so the app never shows a bare number that looks
  measured when it is not. When nothing can answer, the row shows `T=` alone
  and the split has a stated reason.
- v1.6.5, owner order 2026-10-13: the settings control is the owner's own
  settings.png image, copied byte for byte from his Desktop into
  `res/drawable-nodpi/` (512 square, a black gear on transparency, so the file
  itself carries no background tile), tinted from the palette and sitting on
  no plate at all: the drawn gear vector and its two plates are deleted. It
  shares a row with the brand line, so it is centred on "Quant of Rehan"
  rather than on the whole brand block, and the panel's state is a quarter
  turn to the left with a brighter gold, animated back on close. Every line of
  the system status and latest signal tiles now uses the owner's faces (the
  pill LEMON MILK Bold, the detail line and the signal list LEMON MILK Light,
  and the clock no longer forces monospace). The "Trading resumes" sentence is
  retired from the status tile, so a break reads the relay's own condition
  alone, and a volume leader row brackets its volumes:
  `1. CNERGY (B=12,345  S=9,876  T=22,221)`.
  Version 1.6.5, versionCode 19.
- v1.6.6, owner order 2026-10-13 (second note): four refinements of the same
  console. The settings control now stands ON the "Quant of Rehan" baseline
  rather than centred on its row: the XML anchors it to the title and
  `MainActivity.alignSettingsToBrandBaseline` puts its bottom edge on that
  title's own baseline, so the offset follows Bonskin's metrics and the system
  font scale instead of a fixed margin. A diamond rule now divides the system
  status tile from the latest signal tile, so every change of subject on the
  console is marked. The rule that closed the market card from inside it now
  stands immediately after that tile's own boundary, so the divider reads
  between the card and the air below it instead of as part of the card. And the
  ONLINE indicator breathes while the relay reports the market OPEN: a keyframed
  `ValueAnimator` (out, back, repeating, no seam) drives the dot's own opacity
  and size, with the scale applied about the dot's centre so the word beside it
  never moves. A shut market, a midday break, an unreported phase or a hidden
  console leaves the dot still, because a breathing light over a shut market
  would claim activity there is none.
  Version 1.6.6, versionCode 20.
- v1.6.7, owner order 2026-10-13 (third note): three refinements. The settings
  control no longer overflows the header row: its 42dp box carries a 12dp top
  margin, which is the room its baseline translation needs (the box overhangs
  the row by about 9dp at 30sp Bonskin), and the brand row sets
  `clipChildren="false"`, so the guarantee does not depend on one magic
  number once the system font scale moves the line. The cadence sentence
  (`string/scan_cadence`, view `@+id/scan_cadence`) leaves the market card and
  stands immediately after the final diamond rule, separated from it by two
  line breaks, which live as the two leading newlines of the string resource
  so the copy and its spacing cannot drift apart. And the status light's pulse
  is rebuilt: both states breathe, the ONLINE beacon in the palette green
  (`@color/green_halo`, `@color/green_glow`, `@color/green_hi`) and the
  OFFLINE one in the palette red (`@color/red_ring`, `@color/red_core`), which
  means the drawables no longer carry raw hex and the colour of each light is
  one fact in `values/colors.xml`. The pulse runs on a hard 25 frames per
  second: the animator carries only the cycle's clock (linear, repeating) and
  its listener quantises the elapsed time to a 40ms grid, draws nothing when
  the step has not advanced, and shapes the breath with a raised cosine, so
  the rate is the app's rather than the display's and the platform's frame
  delay hint (documented as ignorable under vsync timing) is not relied on.
  Version 1.6.7, versionCode 21.
- v1.6.8, owner orders 2026-10-13 (fourth and fifth notes): two placements.
  The settings control now stands directly beside the "Quant of Rehan" title
  instead of pinned to the row's far edge: `layout_toEndOf` anchors it to the
  title's own right edge, so the pair holds at any screen width and at any
  font scale, with 6dp of margin plus its own 6dp of padding leaving 12dp of
  air between the name and the ink; the vertical anchors (`alignTop` and the
  baseline translation in `MainActivity`) are untouched, so it still stands
  on the brand baseline. And the cadence sentence's separation from the
  final rule is now the layout's own 12dp, the gap the latest signal tile
  has below its rule, so the console's last line sits on the same grid as
  everything above it; the two leading newlines are retired from
  `string/scan_cadence`, whose words stay byte-identical and stay the only
  place they appear. Version 1.6.8, versionCode 22.
- v1.6.9, owner orders 2026-10-14 (sixth, seventh and eighth notes): three
  refinements of the same console. The settings control is centred VERTICALLY
  on the "Quant of Rehan" title now: `layout_centerVertical` replaces
  `layout_alignTop`, and the baseline translation of v1.6.6 is retired with
  its `addOnLayoutChangeListener` and its 12dp overflow margin, so the pair
  reads level at any font scale with no measured pixel; the brand row keeps
  `clipChildren="false"`, which is what still keeps the 42dp box whole.
  The status tile is spaced by one number: the pill had a 10dp top margin
  above a 4dp detail gap, and both are `@dimen/status_gap` (10dp) now, so
  SYSTEM STATUS to ONLINE and ONLINE to KARACHI are the same air; the beacon
  to the word gap moves to `@dimen/status_dot_gap`, the 8dp the pill used to
  carry as a compound drawable's padding. And the status light is rebuilt:
  the beacon is its own `ImageView` inside the badge, because a compound
  drawable cannot be animated by the platform, and the breath is a view
  property animation on that view's alpha and scale, which the platform
  interpolates on the render thread, so no frame of the pulse measures, lays
  out or draws on the UI thread. Only a live market breathes: OFFLINE and
  CHECKING hold a light that is not moving, and the badge announces the state
  through one spoken description while its two children are decoration for the
  reader.
  Version 1.6.9, versionCode 23.
- v1.7.0, owner order 2026-10-15: the market card's quantity fields, the
  estimate mark and the settings control. The B and S columns are back with
  the exact, raw numbers the broker feed produced: `src/data/volume_split.py`
  carries the tape's own counted sides verbatim (`tape_counts`) instead of
  projecting them onto the exchange's session total, so a row reads
  `1. CNERGY (B=12,345  S=9,876  T=22,221)` where B and S are what the tape
  counted and T stays the exchange's own figure. Nothing is scaled or
  rounded on the way in or out, B + S is the tape's counted window rather
  than T, and the row's own label says the counts cover part of the session.
  A row whose split is the day's-range estimate keeps the honest sign, and
  that sign is now drawn by the system face: LEMON MILK does map U+2248, but
  its two bars sit 131 of the font's own 2048 em units apart, so at 13sp
  they merge into a single squiggle and the owner read it as a tilde
  (measured 2026-10-15). The measurement is the fix's reason, not a guess:
  `tests/test_android_app_ui.py` pins the override, and the equals sign of a
  measured count is untouched, since LEMON MILK's U+003D is two clean bars
  363 units apart. A row that has a split but no total keeps both sides and
  closes its bracket, so the quantities are never dropped for want of a T.
  The settings control moves 20% of its own 42dp box to the right and 5% of
  that box higher than the 2026-10-14 centring put it (8.4dp and 2.1dp up,
  declared as `@dimen/settings_shift_x` and `@dimen/settings_shift_y`), as a
  translation, so the anchors beside the title still hold and the shift
  scales with the control rather than with the screen.
  Version 1.7.0, versionCode 24.
- v1.6.1 stated the cadence on the main screen, under the system status pill;
  v1.6.2 moved that sentence into the market card's own foot (owner order
  2026-10-12), so it is read with the volume ranking it describes and the
  interface has no separate bottom block.
- Phone notifications on status changes and new signals, refreshed every 5
  minutes by a watchdog that re-arms itself and survives phone restarts.
  v1.5.1 adds a one time battery optimisation exemption request: see
  "Watchdog and battery" below.

## Branding

Colors come straight from `assets/quant-of-rehan-logo.svg`: deep purple
background (#0B070D, #170D1C), gold frame (#D9A441, #F8CE66), ascending
green candles (#2FAE6F), teal accents (#4A9C95). The launcher icon is the
logo; the status-bar icon is a white gold-diamond-and-candles glyph.
Since v1.3.0 the adaptive icon glyph carries the diamond-and-rule motif
above AND below the candles at mirrored distances (generated by
C:/Users/rehan/quant-tmp/make_icon_v3.py).

## Type (v1.6.4, extended in v1.6.5)

Three faces are bundled, all of them the owner's own files, copied from his
Desktop into `res/font/` with the licences taken from the same zips into
`android/LICENSES/`:

| Resource | Source file | Licence | Used for |
| --- | --- | --- | --- |
| `res/font/bonskin.otf` | `Bonskin.otf` | personal use; commercial needs a purchase (`Bonskin-PersonalUse.txt`) | the app name, "Quant of Rehan" |
| `res/font/lemonmilk_bold.otf` | `LEMONMILK-Bold.otf` | donationware, free for personal use (`LEMONMILK-ReadMe.txt`) | section labels, buttons, the status badge, the index line |
| `res/font/lemonmilk_light.otf` | `LEMONMILK-Light.otf` | as above | the tagline, the card's values, the card's caption |

What each face can draw was measured against its own cmap before it was wired
in, because the app cannot fall back gracefully once a face is applied:

- LEMON MILK (the free tier) maps every lowercase codepoint onto its uppercase
glyph. That is why the labels, buttons, badge, card values and (since v1.6.5)
every line of the system status and latest signal tiles are set in it, which
the owner ordered knowing it reads in capitals. The settings hint keeps the
system face because it is a paragraph; the token field it used to share that
rule with is retired (v1.7.6).
- LEMON MILK has U+2248, the "about" mark the card uses for an estimated
split, so the marked numbers keep the brand face.
- LEMON MILK has no U+25B2 and no U+25BC, the up and down arrows. The arrow
ranges are therefore drawn with the system face by a span in
MainActivity (`ARROW_FACE`), one character each: the arrow, never the number
beside it.
- No bundled face has U+25C6, the brand diamond, so `QorDiamond` sets no
fontFamily at all and the rule's diamond keeps the system face. The U+2699
gear glyph is in none of them either, which is the other reason the settings
control became a vector drawable.
- The brand is 30sp, measured rather than guessed: "Quant of Rehan" advances
6.677 em in Bonskin, so 200dp on a 320dp content width. It carries no
letterSpacing (tracking breaks a script face's joins) and no `textStyle`
(Android would synthesise a bold from a face that already has one weight).
- The brand also keeps `includeFontPadding` at its default. Bonskin's ink for
that exact string reaches 779/1000 em while its typographic ascender is only
730/1000, so the tighter box would shave the top of the capital Q; the default
box uses the wider hhea metrics (1006 / -288), which contain the ink.

`tests/test_android_app_ui.py` parses these tables itself and asserts all of
the above, so a future font swap that drops a glyph fails the suite instead of
shipping empty boxes to the phone.

One platform note: a resource font used from `android:fontFamily` needs
Android 8.0 (API 26). The manifest floor stays at 24; on 24 and 25 the brand
and the labels fall back to the system face, which is cosmetic, and nothing
else in the app depends on it.

## Build in the cloud (the default)

`.github/workflows/android-apk.yml` builds the APK on GitHub Actions. It runs
on manual dispatch and on every merge that touches `android/app/src`, so the
artifact attached to a run is always the commit that shipped. There is no
Gradle project here: the workflow runs the same aapt2, javac, D8, zipalign and
apksigner chain described under the hand build below, installing platform 30
and build-tools 33.0.2 on the runner.

Download the APK from the run's **Artifacts** section (`QuantOfRehan-v<version>`).

Signing is the one thing a runner cannot invent. The phone accepts an update
only when it is signed by the key that installed the running build, so the
workflow reads `ANDROID_KEYSTORE_BASE64` (the keystore, base64 encoded) plus
`ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS` and `ANDROID_KEY_PASSWORD`
from repository secrets. With no keystore secret it still builds and signs
with a freshly generated debug key, which installs only after the old app is
uninstalled; the app stores no account or token, so nothing is lost but the
home screen shortcut. Each run prints the signing certificate, so which key
built an artifact is never a guess.

Owner order 2026-10-19 puts the owner's PC out of this: the hand build below is
documentation of the chain, not the routine way to ship an APK.

## Build (no Gradle, no Android Studio)

Toolchain lives in C:/Users/rehan/android-tools: aapt2 (maven jar), the
platform-30 android.jar, r8's D8, uber-apk-signer, and a JDK 17
(JDK 8 cannot run D8). From the repo root:

```bash
TOOLS=/c/Users/rehan/android-tools
JDK=$(ls -d $TOOLS/jdk-* | head -1)
PLAT=$TOOLS/android-11/android.jar          # platform-30
B=android/app/build
"$TOOLS/aapt2x/aapt2.exe" compile --dir android/app/src/main/res -o $B/res.zip
"$TOOLS/aapt2x/aapt2.exe" link -o $B/app.unaligned.apk -I "$PLAT" \
  --manifest android/app/src/main/AndroidManifest.xml --java $B/gen \
  --auto-add-overlay $B/res.zip
find android/app/src/main/java $B/gen -name "*.java" > $B/sources.txt
"$JDK/bin/javac" -encoding UTF-8 -source 8 -target 8 -classpath "$PLAT" \
  -d $B/classes @$B/sources.txt
mkdir -p $B/dex      # D8 refuses an output directory that does not exist yet
"$JDK/bin/java" -cp $TOOLS/r8.jar com.android.tools.r8.D8 --release \
  --lib "$PLAT" --output $B/dex $(find $B/classes -name "*.class")
python - <<'PY'
import zipfile, shutil
B = "android/app/build"
shutil.copy(f"{B}/app.unaligned.apk", f"{B}/app.apk")
with zipfile.ZipFile(f"{B}/app.apk", "a", zipfile.ZIP_DEFLATED) as z:
    z.write(f"{B}/dex/classes.dex", "classes.dex")
PY
"$JDK/bin/java" -jar $TOOLS/uber-apk-signer.jar -a $B/app.apk --out $B/signed
cp $B/signed/app-aligned-debugSigned.apk \
  /c/Users/rehan/OneDrive/Desktop/QuantOfRehan-v1.7.0.apk
```

The Desktop this machine actually shows is `C:/Users/rehan/OneDrive/Desktop`
(`[Environment]::GetFolderPath('Desktop')`), which is NOT the same folder as
`C:/Users/rehan/Desktop`. A build copied to the wrong one is invisible to the
owner: the v1.6.0 APK went to `C:/Users/rehan/Desktop` and was reported missing.
v1.6.2, v1.6.3 and v1.6.4 were built and copied to the OneDrive Desktop on
2026-10-12, v1.6.5 on 2026-10-13, and v1.6.6 and v1.6.7 the same day, each
with the same aapt2, D8 and signer chain above, from this checkout. v1.6.8
was built on 2026-10-13 and v1.6.9 on 2026-10-14. v1.7.0 (versionCode 24)
is this checkout's source for the 2026-10-15 orders; its toolchain steps above
were run against this tree on 2026-10-15 (aapt2 compile and link, javac, D8),
so the Java and the resources are known to build, and the signed APK is built
by the same chain when the owner wants it on the phone.

**Built and delivered 2026-10-15 (owner order):** the signed v1.7.0 APK was
built from this checkout by the chain above, and copied to
`C:/Users/rehan/OneDrive/Desktop/QuantOfRehan-v1.7.0.apk` while master was at
`7e22080` (PR #98 merged). 535,632 bytes,
SHA-256 `72393aab4ced2099309d2ab40177b3903536f4eb54e2e3131f36eb731972d856`,
zipalign verified, signature verified v2 + v3 (debug key, CN=Android Debug,
expires 2044), and `aapt2 dump badging` reads back
`pk.quantofrehan` `versionCode="24"` `versionName="1.7.0"` with the launchable
`MainActivity`. The Android source tests were green before the build
(50 passed in tests/test_android_app_ui.py and tests/test_android_card_copy.py),
so the source that shipped is the source the tests pin.

## Watchdog and battery

The 5 minute refresh is a best effort schedule, and the app cannot make it
stronger than Android allows. What it already does:

- `AlarmManager.setExactAndAllowWhileIdle(RTC_WAKEUP, now + 5 min)` with a
  broadcast receiver that re-arms itself on every tick, plus a re-arm on
  `BOOT_COMPLETED`, so a phone restart does not silence it;
- the app refreshes on open and on resume, so the cards are never stale
  while the owner is actually looking at them;
- while the console is on screen it polls the relay by itself, every second
  when the relay reports a live session and every 30 seconds otherwise (the
  placeholders of v1.7.1 to v1.7.3 below). This is a foreground loop on the
  main thread's own queue, removed in `onPause`; the watchdog above is
  untouched by it and still beats every five minutes when the app is not open.

What can still delay a background tick: Doze, and OEM battery managers that
kill background work outright (roughly a 9 minute cap, or a stopped alarm, on
the most aggressive phones). The mitigation an app can legitimately ask for
is a battery optimisation exemption. Since v1.5.1 the app requests it once,
quietly, on first run, and the Arm button requests it again on demand; the
power user can also confirm it under Settings, Apps, Quant of Rehan, Battery.
If the exemption is granted the watchdog keeps its cadence; if it is refused
the app still refreshes whenever it is opened or resumed.

The Always Classy face (res/font/always_classy.ttf, licence in
android/LICENSES/) was bundled for the motivational panel. That panel is
gone as of v1.5.0, so the font is no longer referenced by any layout; it is
kept in the tree with its licence rather than deleted.

- v1.7.1, owner order 2026-10-16: the console keeps up with the live cadence.
  The scan moved to GitHub Actions minutes and the Cloudflare relay at 30
  seconds (SO-13, `config.SCAN_INTERVAL_SECONDS`), so the card's cadence
  sentence now reads "every 30 seconds when the market is open" instead of the
  retired local tick's 4 minutes, and the console repaints at that cadence for
  as long as it is on screen (`MainActivity`'s `tick` loop, removed in
  onPause) rather than once per open. The background watchdog is unchanged at
  five minutes and `Watcher.WATCHDOG_MS` says why: an AlarmManager wake is not
  a poll, and `setExactAndAllowWhileIdle` is capped inside Doze, so a 30
  second alarm would advertise a cadence Android will not honour. Version
  1.7.1, versionCode 25.
- v1.7.2, owner order 2026-10-16 (second note of the day): three changes to
  the console, all of them about latency and legibility.

  **The settings control moves again.** The order is +15% of the control's own
  42dp box to the right and +5% of it DOWN from where it already stood, and
  the orders stack because a translation on a leaf view never changes layout:
  20 + 70 + 15 = 105% right (44.1dp) and 5 + 15 - 5 = 15% up (6.3dp, a
  negative translation). `dimens.xml` states the sum and the three orders that
  produced it, and the UI test pins the arithmetic rather than a pair of
  magic numbers.

  **The settings menu is now exclusive.** Tapping the gear used to open the
  panel under a console that stayed on screen. Now the three tiles (system
  status, latest signal, the market card), the three diamond rules between and
  after them and the cadence sentence all leave together, so the menu is the
  only thing on the view, as ordered. They leave as `GONE` rather than
  `INVISIBLE`: the menu takes the space instead of leaving a hole, and a
  hidden view is out of the accessibility tree, so a screen reader reads the
  menu alone. The state is one boolean field (`MainActivity.settingsOpen`) and
  the views are drawn FROM it, never asked: the toggle returns early when the
  value has not changed, so a repeated tap cannot re-run the animations or
  thrash the view tree, and the seven views are looked up once in onCreate and
  toggled in one loop rather than by seven independent calls.

  **The console polls by itself, once a second while the market is open.**
  This replaces the 30 second repaint of v1.7.1 and any manual refresh with an
  automatic live poll. The interval comes from the RELAY's own answer
  (`market_open`, carried into `marketOpenSeen` by `render`), never from the
  phone's clock, so a closed market, a midday break or a weekend falls back to
  the 30 second idle poll and the app still obeys SO-8. One method
  (`MainActivity.scheduleNext`) schedules every tick, so the cadence is
  decided in exactly one place. Two guards keep it honest: a single in-flight
  flag means a slow round skips a tick instead of queueing one (and every path
  of a round clears it, including the error path), and the ONE SECOND round is
  `Watcher.fetchLive`, which reads `/health` and `/signals` only. The market
  card is deliberately not in that round: the relay rebuilds it from the
  exchange page about every five minutes, so it rides along once every
  `CARD_EVERY_SECONDS` (30) live rounds, and a light round reports a null card
  which `render` reads as "leave the card on screen exactly as it is". One
  request a second, on the pair that actually moves. Version 1.7.2,
  versionCode 26.
- v1.7.3, owner order 2026-10-16 (fourth note of the day): the reported
defect was "the app currently fails to auto-refresh every second, despite the
footer indicating a 30-second scan cycle". There were three causes, and all
three are fixed.

  **The cadence was decided before the first answer arrived.** `onResume`
  scheduled the next round through `scheduleNext`, whose interval is a
  function of the relay's own `market_open` as carried by `marketOpenSeen`,
  and that field is `false` on a fresh process. So an OPEN market was polled
  at the 30 second idle interval until a whole idle round had completed, which
  is exactly what "it never refreshes every second" looks like from the
  phone. `render` now re-decides the cadence the moment the answer lands, by
  calling the same single scheduling point: `scheduleNext` removes the one
  runnable before re-posting it, so the extra call cannot stack a second loop.
  The owner's own instruction is unchanged and still honoured: the session
  comes from the relay, never from the phone's clock (SO-8).

  **A one second repaint was invisible.** The relay's `karachi_now` is
  formatted by `cloud/worker.js`'s `hhmm`, which prints `HH:MM` and no
  seconds, so a perfect one second poll redrew a byte-identical screen for up
to sixty seconds. The status tile therefore also carries the app's own
  contact line, to the second: `Live: updated HH:MM:SS PKT, polling every 1 s`
  (`string/app_live`), built in Asia/Karachi and taking the interval from
  `Watcher.FAST_POLL_MS` rather than from a literal, so the sentence and the
  loop cannot disagree. It is the phone's record of its own last answer, shown
  beside the relay's Karachi line and never instead of it, only while the
  relay reports a live session, and it states no market fact (SO-3).

  **The panel described a different cadence.** The hint under the settings
  looked like a promise that the console repaints every 30 seconds. The
  sentence the owner was reading on the console itself
  (`string/scan_cadence`) is the SCANNER's cadence, which really is 30 seconds
  in the cloud (SO-13) and stays byte-identical; the hint, which is help text,
  now states the two cadences apart: every second while the market is open,
  every 30 seconds when it is shut and for the exchange-backed card.

  **The settings press gradient was sliced.** The control is translated
  44.1dp right of where the brand row anchors it, and a translation moves the
  DRAWN box without moving any measured bound: Android clips a child to its
  parent's bounds unless the parent says otherwise, so the gold flash was cut
  along the header's right and top edges. Every ancestor of the control now
  carries `clipChildren="false"` (scroll view, content column, header, brand
  row; the scroll view is the root of the layout and fills the window, so its
  own no-clip changes nothing else), and `MainActivity.applySettingsShift`
  clamps the ORDERED offset to the pixels the screen actually has, measured
  after the first layout between the control's own right edge and the window's
  (`Math.min(orderedX, Math.max(0f, room))`). A wide phone gets the owner's
  offset in full; a narrow one loses only the pixels it does not have.

  **The offline light is the online light in red, and it is still.** The
  owner's order was exact: the OFFLINE icon should be "exactly like the ONLINE
  icon just in red color but also not breathing ... there should be a round
  ball type structure should also be inside that thick line just like ONLINE
  icon has it". It used to be a thin ring around a hollow thick ring, which
  read as a different symbol rather than as the same light unlit. It is now
  layer for layer the online beacon: the same `pathData`, the same 1.3 halo
  stroke, the same 6.4 disc and 3.7 ball, in the palette red
  (`@color/red_ring`, `@color/red_core`, and the new `@color/red_hi` for the
  ball). The stillness needs no code of its own: the breath gate
  (`breathIfOnline`) starts the pulse only for a live market, so the red light
  is only ever returned to rest (SO-3: a pulse over a shut market would claim
  trading there is none).

  **The header names the index and drops the timezone note.** `string/tagline`
  is now `PSX's KMIALL INDEX · SIGNAL-ONLY`: the label "PSX KMIALL" became
  "PSX's KMIALL INDEX" and "KARACHI TIME" left the header. The clock itself is
  not retired; it stands in the system status tile, where a reader looks for
  it, and every time in the app stays Asia/Karachi (SO-8). Version 1.7.3,
  versionCode 27.
- v1.7.4, owner order 2026-10-18: the live relay card, including KMIALL
  volume leaders, is read on each one-second foreground refresh while the
  market is open. This fetches the latest broker snapshot; the source timestamp
  remains authoritative, so a one-second UI poll does not claim a new broker
  tick. The session remains the relay's authority. The footer deliberately
  keeps SO-13's 30-second scanner wording, not the phone display cadence. The
  settings hint describes available broker data without claiming an upstream
  refresh interval, and its SETTINGS heading is centered in the tile.
  Version 1.7.4, versionCode 28.
- v1.7.5, owner order 2026-10-19: the console no longer repaints an answer
  that has not changed. It polls once a second on a live market, while the
  relay's own clock has minute resolution and its card moves only when the
  cloud capture publishes, so most answers were identical, and every one of
  them still re-measured and re-laid out three tiles and allocated a fresh
  status badge drawable. `RenderGate` (plain Java, no Android imports) now
  compares the answer with the one on screen and `paint()` runs only on a
  change; the two badge backgrounds are built once; `onResume` resets the gate
  so the first answer after a pause always repaints, which is what restarts
  the status breath. The gate is exercised on the JVM by
  `tests/test_android_render_gate.py`, not only read as source. Nothing about
  the data changes: the relay's timestamp is still the only freshness claim.
  Version 1.7.5, versionCode 29.
- v1.7.6, owner order 2026-10-19 (second note of the day): the dashboard is
  cleaned and the numbers are live. The OFFLINE tile is a dark red gradient
  (`red_deep` to `red_deep_edge`, white ink at about 10:1 on the lighter end)
  instead of a pale tint; the latest signal tile shows only Entry Price, Exit
  Price and Stop Loss, and collapses a no-trade day to the words NO TRADE, so
  the `QoR signals <date>` header, the timestamps and the rule paragraphs that
  came with the text card never reach the screen; the settings tile loses the
  admin token field, its save button and the paste instructions, keeping the
  relay link and the watchdog arm. The phone holds no credential: the relay's
  GET /signals is a public read (its POST stays admin gated). The KSE100 line
  and every leader price are overlaid from the relay's live broker snapshot
  on each round, and the "feed status unconfirmed" sentence is retired in
  favour of the broker's own HH:MM:SS stamp on the index line, so a number
  always says when it was taken. Display cadence stays one second on a live
  market with the render gate absorbing identical answers. (That entry left
  the STRATEGY scan at 30 seconds; the owner's order later the same day moved
  it to one second, see v1.7.7.)
  Version 1.7.6, versionCode 30.
- v1.7.7, owner order 2026-10-19 (third note of the day): real-time, end to
  end. The strategy scan moves from 30 seconds to a one second request
  (`config.SCAN_INTERVAL_SECONDS = 1`, `intraday-session.yml --interval 1`),
  and the cadence sentence on the console now reads "every second". Measured
  cost of one cycle on the real 2026-10-13 session tape is 2.9s, so one second
  is the request rather than the achieved rate: the loop starts the next scan
  as soon as that cycle ends (about every three seconds), never queues a
  backlog, and its log no longer prints a "sleeping 0s" line per cycle. The
  phone's part is genuinely one second: it repaints every second, takes the
  newest `/quotes` snapshot the relay holds, and the broker's own HH:MM:SS
  stamp on the KSE100 line advances when the capture does. The signal tile's
  reader is now `SignalText` (plain Java, no Android imports), so the ticker
  and the three prices are parsed and tested on the JVM instead of only read:
  the sentence form the daily-locked path writes ("HCAR entered at 203.0,
  target 207.06") now yields a signal instead of "Signal unavailable".
  Version 1.7.7, versionCode 31.
- v1.7.8, owner order 2026-10-20: the console stops showing yesterday as if it
  were today. The signal tile compares the card's own session date against the
  relay's Karachi date and prints "NO CALL RIGHT NOW" when they differ, so
  Friday's HCAR row can no longer sit on a Tuesday screen; an empty card says
  the same words instead of going blank, and the old "no signals" line is
  retired. B and S lose the two approximation signs that the shipped face drew
  as tildes, and the split is now recomputed in the relay from every fresh
  frame instead of being carried forward from the pushed card, so a moving
  total can no longer sit beside frozen buy and sell quantities; the closing
  EST tag says when the pair is the day's-range estimate. The KSE100 line
  prints nothing rather than an eight character slice of a date when the relay
  sends a date with no clock on it. A search control stands to the left of the
  gear on the same line, and its panel filters the relay's own symbol list on
  every keystroke (F lists every F symbol, FF narrows to FFC and FFL), then
  asks the relay for that one symbol's B, S and T. The ONLINE badge takes the
  OFFLINE tile's gradient in green, and the background watchdog arms at one
  second instead of five minutes.
  Version 1.7.8, versionCode 32.
- v1.7.9, owner order 2026-10-20 (third note): the console becomes a clock, not
  a refresh. The signal tile's empty state is one sentence, "NO SIGNAL
  AVAILABLE RIGHT NOW", on both the not-yet-read and the no-trade path, so
  "NO TRADE" can no longer reach the screen. The KSE100 line keeps the index
  and its move and drops the clock after the percentage; the top three carry
  "B=" and "S=" with no EST tag, on the card and in the search answer alike.
  The search control moves a further 15% of its own 42dp box to the right
  (net 50.4dp) and its glass is a stroked vector instead of the tinted
  search.png disc, so the glass is see-through and only the ring and the
  handle are gold. The one-second round now makes two relay reads instead of
  three (the relay already merges the live quote hub into /market), so the
  paint actually lands every second, and the search rows' prices are read once
  per tick instead of once per five. Notifications are limited to four events:
  market online, market offline, market break and a real signal.
  Version 1.7.9, versionCode 33.
- v1.8.0, owner report 2026-10-20 (14:07 PKT scan): the searched stock no
  longer vanishes the second after the tap. The search rows now keep their
  views across the one-second price ticks and re-style in place, so a tick
  cannot tear the list down and drop the stock the owner just opened. The
  pinned selection keeps its B/S answer under it and a live tail restamped
  every tick: the stock's own price and percentage, green for a positive move
  and red for a negative one, true nulls carried in neutral ink. The search
  control moves a further 15% of its own 42dp box to the right (net 57.96dp).
  Version 1.8.0, versionCode 34.
- v1.8.1, owner orders 2026-10-21 (morning): the VOLUME NOW tile label is
  gone, the search box's hint reads "Search for a KMIALL scrip", the
  "NO KMIALL SYMBOL STARTS WITH THAT YET." sentence under the box is gone
  (a no-match prints nothing), the searched stock's own price and
  percentage appear exactly once (the coloured form: green when it is up,
  red when it is down, neutral ink only when the venue reports no move),
  the fetched B and S counts print in their own colours (green buy, red
  sell) and those colours survive the one-second restamp because the base
  line is a spannable now, and the search glass moves a further 10% of its
  own 42dp box to the right (net 62.16dp).
  Version 1.8.1, versionCode 35.
- v1.8.2, owner order 2026-10-21 (afternoon, superseding the 2026-10-11
  watch-only rule): the quant scans the market's own pre-market (09:00-09:15)
  and post-market (Mon-Thu 15:32-15:49, Friday 16:32-16:49) windows on the
  live broker feed every second, and the phone's cadence sentence says so:
  "Quant will be scanning the market every second when the market is open,
  and in the pre-market and post-market windows too." The market-open,
  break and closed notifications keep the owner's exact 2026-10-11 wording;
  they name the exchange's state, which the pre and post windows never
  change. Version 1.8.2, versionCode 36.
- v1.8.3, owner orders 2026-10-21 13:07-13:08: on the pinned search line
  the gap between the volume group and the price is one space (it was
  three), the closed search panel's bottom gap equals its top gap (the
  results and status rows are hidden while empty, so their margins can no
  longer open a hole under the box, and the panel's own 10dp above and
  below the box are then the gap), and the footer sentence is replaced
  with the exact wording the owner dictated: "QUANT WILL BE SCANNING THE
  LIVE/POST/PRE MARKET EVERY SECOND." Version 1.8.3, versionCode 37.
- v1.8.4, owner report 2026-10-21 13:30 and orders at 14:19: the v1.8.3 gap
  law had a regression (the empty-by-default results and status rows shipped
  them as layout GONE so no code showed them again, and the whole search
  output vanished): the rows and the pinned line are now flipped
  visible/hidden by their content in MainActivity, never by the layout.
  Second: the search box and the KSE100 line drop their extra 10dp top
  margins, so both tiles read one gap above and below from the panel's own
  16dp padding. Third: the volume group's separators between B, S and T
  are one space (it was two), so CNERGY's five million B and twenty-seven
  million S no longer wrap the T onto its own line. Fourth: the footer is
  replaced with the exact wording dictated at 14:19: "QUANT WILL BE
  SCANNING THE LIVE, THE POST & THE PRE MARKET EVERY SECOND." (the
  ampersand escaped in XML). Version 1.8.4, versionCode 38.
- v1.8.5, owner report 2026-10-21 14:51: the pinned search answer's money
  tail keeps exactly ONE space between the price and the percentage (it
  had two), and on the KSE100 card every leader's name, B, S and T stand
  on ONE line: the group's separators are non-breaking spaces (U+00A0) so
  a wide row can never wrap mid group, and the tile carries its own 11.5sp
  so the widest row the relay can publish fits the panel without dropping
  a single digit of the feed's counts. Version 1.8.5, versionCode 39.
- v1.8.6, owner order 2026-10-21 15:15: one type size for the whole console.
  The KSE100 rows go back to the body's 13sp (v1.8.5 had shrunk them to
  11.5sp to force one line) and they still stand on one line, because the
  row now wins its width from the tile: it spends 8dp of each 16dp panel
  padding through -8dp side margins and tightens only its own tracking, to
  -0.02. Measured against the bundled LEMON MILK Light, the widest rank line
  the card has shown, "2. CNERGY (B=12,626,814 S=25,253,629 T=37,880,443)",
  advances 342.1dp at that size and tracking against 347dp of line, and nine
  digit counts still fit at 344.5dp. The search box and its result rows drop
  from 15sp to 13sp, and the brand tagline and the footer sentence, the last
  two 10sp lines, join the body size. Only the bold headings keep a size of
  their own: the 17sp index, the 11sp tile labels and the 12sp buttons.
  Version 1.8.6, versionCode 40.

- v1.8.7, owner order 2026-10-21 15:35: the volume group reads as a sentence,
  `2. CNERGY (B=12,626,814, S=25,253,629 & T=37,880,443)`: a comma after B and
  an ampersand before T, both held by non-breaking spaces so the group still
  cannot break across two lines. The two characters cost width at the body's
  13sp, and the row takes it from the tile rather than from the type: 6dp of
  each 16dp panel padding through its -10dp side margins plus -0.035
  tracking, measured at 348.5dp of the 358dp line the tile gives it. The
  search and settings tiles are bracketed like every other tile: a diamond
  rule above the search panel and one below the settings panel, each arriving
  and leaving with its own menu. The search box centres its one line with the
  font's padding out of the measured height, so its air is the panel's 16dp
  above and below, and its hidden rows now start GONE in the layout as well as
  through the code that flips them. The placeholder sentence "NO SIGNAL
  AVAILABLE RIGHT NOW" takes the body's soft ink instead of the bright ink it
  inherited from the real-call branch. Version 1.8.7, versionCode 41.

**Built and delivered 2026-10-21 (v1.8.6):** the signed v1.8.6 APK was built
on GitHub Actions from the merge of PR #73 (run 39584915632), downloaded from
the run's artifact and copied to
`C:/Users/rehan/OneDrive/Desktop/QuantOfRehan-v1.8.6.apk`. SHA-256
`f96b3f978b1ed5fda365dac7c9510fa14781a167cb3598a49b1e5aae9e79b0f4`,
and the run's `badging.txt` reads back `pk.quantofrehan`,
`versionCode="40"`, `versionName="1.8.6"`, with the launchable
`MainActivity`. The shipped layout was read back out of the APK's own
resource table: 30sp brand, 17sp index, and 13sp for the tagline, the search
box and the status word, with the leaders row carrying no size of its own
(so it inherits the body's 13sp) and only its -0.02 tracking and -8dp side
margins; `style/QorCaption` ships at 13sp. The Android tests (105 across app
ui, card copy, the render gate and the signal reader) were green before the
build.

**Built and delivered 2026-10-21 (v1.8.5):** the signed v1.8.5 APK was built
on GitHub Actions from the merge of PR #70, downloaded from the run's
artifact and copied to
`C:/Users/rehan/OneDrive/Desktop/QuantOfRehan-v1.8.5.apk`. SHA-256
`d6b9f5c552e770d212f7097d056f356d553a0fe1e3a78a6aeb99666189197676`,
and the run's `badging.txt` reads back `pk.quantofrehan`,
`versionCode="39"`, `versionName="1.8.5"`, with the launchable
`MainActivity`. The shipped footer sentence was read back from the
resource table, and the Android tests (90 across app ui, card copy and
the render gate) were green before the build.

**Built and delivered 2026-10-21 (v1.8.4):** the signed v1.8.4 APK was built
on GitHub Actions from the merge of PR #68, downloaded from the run's
artifact and copied to
`C:/Users/rehan/OneDrive/Desktop/QuantOfRehan-v1.8.4.apk`. SHA-256
`977bba16cc7eeef33ff56db7fef68ff15eb26590ce55d3cb4fe97aef829b959f`,
and the run's `badging.txt` reads back `pk.quantofrehan`,
`versionCode="38"`, `versionName="1.8.4"`, with the launchable
`MainActivity`. The shipped resource table was read back: the dictated
14:19 footer sentence is in the APK byte for byte, the 13:08 wording is
gone, and the Android tests (89 across app ui, card copy and the render
gate) were green before the build.

**Built and delivered 2026-10-21 (v1.8.3):** the signed v1.8.3 APK was built
on GitHub Actions from the merge of PR #66, downloaded from the run's
artifact and copied to
`C:/Users/rehan/OneDrive/Desktop/QuantOfRehan-v1.8.3.apk`. SHA-256
`01260b5dd8f0efc6904cb626cbf07b7cf4f70f21b22df3327149939d728c5750`,
and the run's `badging.txt` reads back `pk.quantofrehan`,
`versionCode="37"`, `versionName="1.8.3"`, with the launchable
`MainActivity`. The shipped resource table was read back and carries the
dictated footer sentence, with the retired wording gone from the APK, and
the Android tests (89 across app ui, card copy and the render gate) were
green before the build.

**Built and delivered 2026-10-21 (v1.8.2):** the signed v1.8.2 APK was built
on GitHub Actions from the merge of PR #64, downloaded from the run's
artifact and copied to
`C:/Users/rehan/OneDrive/Desktop/QuantOfRehan-v1.8.2.apk`. 543,896 bytes,
SHA-256
`83bf64b6d8f8273a6df4bcb7df0a6ee3afe30b3ff74450eadebd989271734fe5`,
and the run's `badging.txt` reads back `pk.quantofrehan`,
`versionCode="36"`, `versionName="1.8.2"`, with the launchable
`MainActivity`. The run's `certificate.txt` carries the repository
keystore signer (CN=Android Debug, SHA-256
`8a4cdbe4b445b444771674cff88200dd3b0164a06d84426e2629a4ca89bdc4cc`), so
the phone accepts this as an update to the running build. The resource
table inside the shipped APK was read back and carries the new cadence
sentence, and the Android tests (85 across app ui, card copy and the
render gate) were green before the build.

**Built and delivered 2026-10-19 (v1.7.7):** the signed v1.7.7 APK was built
from this checkout with the toolchain above and copied to
`C:/Users/rehan/OneDrive/Desktop/QuantOfRehan-v1.7.7.apk`, one file under one
name. 539,728 bytes, SHA-256
`7d6f63b516d7485035b19944b1383e5330e3c3a1672a7729c50e7ac2600bbc78`,
zipalign verified, signature verified v2 + v3, and `aapt2 dump badging` reads
back `pk.quantofrehan` `versionCode="31"` `versionName="1.7.7"` with the
launchable `MainActivity`. The built resource table was read back to prove
what shipped: `string/scan_cadence` reads "Quant will be scanning the market
every second when the market is open.", `string/signal_none` and
`string/signal_unavailable` are present, and no `token_box` or
`market_feed_status` is declared anywhere. `SignalText` (and not the retired
`valueAfterLabel` helper), `RenderGate`, `applyLiveQuotes` and `brokerClock`
are all in the shipped `classes.dex`. The Android tests and the SignalText
JVM probe were green before the build.

**Built and delivered 2026-10-19 (v1.7.6):** the signed v1.7.6 APK was built
from this checkout with the toolchain above and copied to
`C:/Users/rehan/OneDrive/Desktop/QuantOfRehan-v1.7.6.apk`, one file under one
name. 539,728 bytes, SHA-256
`e1db260dd816422c24f7c310b739f6fd9505f86c728c76d59715668542932923`,
zipalign verified, signature verified v2 + v3, and `aapt2 dump badging` reads
back `pk.quantofrehan` `versionCode="30"` `versionName="1.7.6"` with the
launchable `MainActivity`. The built resource table was read back to prove
what shipped: zero resources mention `market_feed_status` or
`market_feed_unknown`, `color/red_deep`, `red_deep_edge`, `red_deep_line` and
`on_red` are present, `string/signal_none` is present, and no `token_box` is
declared anywhere. `applyLiveQuotes` and `RenderGate` are both in the shipped
`classes.dex`. The Android tests were green before the build.

**Built and delivered 2026-10-19:** the signed v1.7.5 APK was built from this
checkout with the toolchain above and copied to
`C:/Users/rehan/OneDrive/Desktop/QuantOfRehan-v1.7.5.apk`, one file under one
name. 539,728 bytes, SHA-256
`3969d426d45e25a69b75854f3798880a8c04968631002e35dedf45a9717b30b0`,
zipalign verified, signature verified v2 + v3, and `aapt2 dump badging` reads
back `pk.quantofrehan` `versionCode="29"` `versionName="1.7.5"` with the
launchable `MainActivity`. `RenderGate` is present in the shipped
`classes.dex`, so the gate in the APK is the gate the JVM probe exercised. The
Android tests were green before the build (69 source tests plus the JVM probe),
so the source that shipped is the source the tests pin.

**Built and delivered 2026-10-18:** the signed v1.7.4 APK was built from this
checkout with the toolchain above and copied to
`C:/Users/rehan/OneDrive/Desktop/QuantOfRehan-v1.7.4.apk`. Its package version,
zip alignment, and signature verification were checked after the build.

**Previous v1.7.3 build (2026-10-16):** the signed APK was copied to
`C:/Users/rehan/OneDrive/Desktop/QuantOfRehan-v1.7.3.apk`, 535,632 bytes,
SHA-256 `6a8c13c6d2d3a08b44ff7196e8661305787718659336f30bbe9105fb5b0e9ab7`,
with zip alignment and v2/v3 debug signature verified. Its manifest declared
`pk.quantofrehan`, versionCode 27, versionName 1.7.3.

The Android source tests are in `tests/test_android_app_ui.py` and
`tests/test_android_card_copy.py`; the current verification results are
reported with this release rather than copied from the older build record.

**Built and delivered 2026-10-16 (owner order):** the signed v1.7.2 APK was
built from this checkout by the chain above and copied to
`C:/Users/rehan/OneDrive/Desktop/QuantOfRehan-v1.7.2.apk`, one file under one
name. The first delivery of this build also carried a second name,
`QuantOfRehan-v1.7.2-live-1s-poll.apk`, and a copy in the non synced
`C:/Users/rehan/Desktop`; all three were the same 535,632 bytes, so the owner
saw two identical installers side by side and asked which one to use (owner
order 2026-10-16, third note: **one build, one file, one name**). The alias
and the extra copy are removed and the signed build output in the repo,
`android/app/build/signed/app-aligned-debugSigned.apk`, is the off Desktop
backup. 535,632 bytes, SHA-256
`74d2afe88d15c43e1d4198cd405c7389facef7c887902c92bce524c5991f7ec3`,
zipalign verified, signature verified v2 + v3 (debug key, CN=Android Debug,
expires 2044), and `aapt2 dump badging` reads back `pk.quantofrehan`
`versionCode="26"` `versionName="1.7.2"` with the launchable `MainActivity`.
The Android source tests were green before the build (57 passed, 32 subtests in
tests/test_android_app_ui.py and tests/test_android_card_copy.py), and the
built resource table was read back to prove what shipped: the six new view ids
are present, `dimen/settings_shift_x` compiles to 44.1dp and
`dimen/settings_shift_y` to -6.3dp (aapt2 renders a negative dimension as its
512 bias, so it prints as 505.700012dp: measured against a probe resource of
-8.4dp, which prints as 503.600006dp), and `string/scan_cadence` still reads
"Quant will be scanning the market every 30 seconds when the market is open."

**Built and delivered 2026-10-16 (owner order):** the signed v1.7.2 APK was
built from this checkout by the chain above and copied to
`C:/Users/rehan/OneDrive/Desktop/QuantOfRehan-v1.7.2.apk`, one file under one
name. The first delivery of this build also carried a second name,
`QuantOfRehan-v1.7.2-live-1s-poll.apk`, and a copy in the non synced
`C:/Users/rehan/Desktop`; all three were the same 535,632 bytes, so the owner
saw two identical installers side by side and asked which one to use (owner
order 2026-10-16, third note: **one build, one file, one name**). The alias
and the extra copy are removed and the signed build output in the repo,
`android/app/build/signed/app-aligned-debugSigned.apk`, is the off Desktop
backup. 535,632 bytes, SHA-256
`74d2afe88d15c43e1d4198cd405c7389facef7c887902c92bce524c5991f7ec3`,
zipalign verified, signature verified v2 + v3 (debug key, CN=Android Debug,
expires 2044), and `aapt2 dump badging` reads back `pk.quantofrehan`
`versionCode="26"` `versionName="1.7.2"` with the launchable `MainActivity`.
The Android source tests were green before the build (57 passed, 32 subtests in
tests/test_android_app_ui.py and tests/test_android_card_copy.py), and the
built resource table was read back to prove what shipped: the six new view ids
are present, `dimen/settings_shift_x` compiles to 44.1dp and
`dimen/settings_shift_y` to -6.3dp (aapt2 renders a negative dimension as its
512 bias, so it prints as 505.700012dp: measured against a probe resource of
-8.4dp, which prints as 503.600006dp), and `string/scan_cadence` still reads
"Quant will be scanning the market every 30 seconds when the market is open."

The APK is signed with the local debug key (v2+v3), which is enough for
direct installation on the owner's phone. Install: copy the APK to the
phone (or open the OneDrive app), allow install-from-unknown-apps for the
source, install, open, arm the watchdog, and allow notifications. Since
v1.7.6 there is no token to paste: the console reads the relay's public
signal card by itself.
