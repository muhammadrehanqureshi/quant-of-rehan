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
- The pill follows the relay's `market_state` phase and carries the shipped
  glyphs (U+2713 check, U+2717 cross) from string resources, with a spoken
  accessibility description, so a screen reader never reads a bare
  "multiplication X".
- Owner order 2026-10-10 retired "PSX session closed". The exchange's midday
  break now reads "Market is on a break right now (trading resumes 14:32 PKT)"
  and every other shut state reads "Market is closed now.". A phase the relay
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
  at most five minutes old.
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
  `1. CNERGY   B=12,345  S=9,876  T=22,221` on the first line and
  `PKR 12.52 up 1.05%` on the second, where B and S are the session's buy and
  sell volumes and T is the exchange's own total.
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
  /c/Users/rehan/OneDrive/Desktop/QuantOfRehan-v1.6.3.apk
```

The Desktop this machine actually shows is `C:/Users/rehan/OneDrive/Desktop`
(`[Environment]::GetFolderPath('Desktop')`), which is NOT the same folder as
`C:/Users/rehan/Desktop`. A build copied to the wrong one is invisible to the
owner: the v1.6.0 APK went to `C:/Users/rehan/Desktop` and was reported missing.
v1.6.2 and v1.6.3 were built and copied to the OneDrive Desktop on 2026-10-12.

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
