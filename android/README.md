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
  "multiplication X" and the state never depends on a font. Since v1.6.7 that
  light breathes in both states, in the palette green for ONLINE and the
  palette red for OFFLINE, at a hard 25 frames per second (owner order
  2026-10-13, third note).
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
- A signals panel fed by the relay's `/signals` feed (admin token required,
  stored once in the app).
- The market card, third box (v1.5.0, extended in v1.6.0, v1.6.2 and v1.6.3): the
  KSE100 index with its points and percentage, then the three KMIALL stocks
  with the highest current session volume, each with its day's percentage
  change (green up, red down) and its volume. The relay builds it from the
  PSX Data Portal's own pages and caches it for five minutes, so the card is
  at most five minutes old. Since v1.6.7 the console closes with the cadence
  sentence under the last diamond rule, separated from it by two line breaks,
  instead of carrying it inside the card (owner order 2026-10-13, third note).
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
  card's foot now reads, verbatim: "Quant will be scanning the market every
  4 minutes when the market is open."
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
the owner ordered knowing it reads in capitals. The settings hint and the
relay token field keep the system face: the hint is a paragraph, and a pasted
token must render exactly as pasted.
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
  /c/Users/rehan/OneDrive/Desktop/QuantOfRehan-v1.6.7.apk
```

The Desktop this machine actually shows is `C:/Users/rehan/OneDrive/Desktop`
(`[Environment]::GetFolderPath('Desktop')`), which is NOT the same folder as
`C:/Users/rehan/Desktop`. A build copied to the wrong one is invisible to the
owner: the v1.6.0 APK went to `C:/Users/rehan/Desktop` and was reported missing.
v1.6.2, v1.6.3 and v1.6.4 were built and copied to the OneDrive Desktop on
2026-10-12, v1.6.5 on 2026-10-13, v1.6.6 the same day, and v1.6.7 the same
day (built with the same aapt2, D8 and signer chain above, from this
checkout).

## Watchdog and battery

The 5 minute refresh is a best effort schedule, and the app cannot make it
stronger than Android allows. What it already does:

- `AlarmManager.setExactAndAllowWhileIdle(RTC_WAKEUP, now + 5 min)` with a
  broadcast receiver that re-arms itself on every tick, plus a re-arm on
  `BOOT_COMPLETED`, so a phone restart does not silence it;
- the app refreshes on open and on resume, so the cards are never stale
  while the owner is actually looking at them.

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

The APK is signed with the local debug key (v2+v3), which is enough for
direct installation on the owner's phone. Install: copy the APK to the
phone (or open the OneDrive app), allow install-from-unknown-apps for the
source, install, open, paste the relay admin token from .env, arm the
watchdog, and allow notifications.
