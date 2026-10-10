# Android companion app update, 2026-10-10

Five requested changes. Four of them were **already implemented in the repo**,
and the phone's APK is current. The reason the screenshot does not show them is
that the **deployed Cloudflare relay is an older revision** than the repo, so it
never sends the fields the app renders. This document says what was genuinely
missing, what was changed, how to integrate it, and exactly what was verified.

---

## 1. The finding that explains most of the request

The app renders only what the relay sends. Live evidence, fetched from the
deployed worker, compared with the repo's `cloud/worker.js`:

| what the app needs | deployed relay returns | repo source emits |
|---|---|---|
| `market_state` on `/health` | **absent** (keys: `karachi_now, market_open, next_event, ok, paired, service`) | present |
| `market_state` on `/market` | **absent** | present |
| `change_pct` per leader | **absent** (leader keys: `basis, price, symbol, volume`) | present |
| `buy_volume` / `sell_volume` | **absent** | `null` at the edge, real values on a PC push |
| `volume_split_basis` | **absent** | present |

Consequences visible in the screenshot, each explained by a missing field:

* `PSX session closed.` is the app's **empty-phase fallback** in
  `Watcher.phaseLine`. The relay sent no phase, so the app refused to guess and
  fell back. That is why the requested copy never appears.
* The three leaders show `T=` and `Rs` but **no percentage**, because
  `change_pct` was never in the payload.
* There is **no `B=`/`S=` split**, because the edge cannot split volume (see
  section 5).

The APK itself is current: `android/app/build/signed/...` was rebuilt today at
11:15, matching the screenshot time of 11:53, and the installed app is v1.6.0.
So the app was never the problem for items 2, 3 and 4. **The fix for those is a
relay deployment, not an app change.**

## 2. Item by item reconciliation

| # | request | status before this change | action taken |
|---|---|---|---|
| 1 | checkmark and cross instead of casual icons | already shipped: `U+2713` / `U+2717` | moved into string resources and given accessibility descriptions |
| 2 | "PSX session closed" becomes "Market is closed now" / "on a break right now" | break and holiday wording existed, but the **empty-phase fallback still said "PSX session closed."** | replaced with the owner's wording, sourced from `market_state` |
| 3 | top 3 KMIALL with percentage movement | rendered already, but the relay never sent `change_pct` | app side already correct, hardened with null-safe typing. **Needs relay deploy** |
| 4 | buy / sell / total volume | rendered already when a genuine split exists | app side already correct. **Needs the PC tick capture, not an app change** |
| 5 | footer "KSE100 index as of [date and time]" | already shipped as `Index as of <asof> PKT` | unchanged, verified present in the built APK |

## 3. What was actually changed

### 3.1 Copywriting, now in string resources

`android/app/src/main/res/values/strings.xml` gains the owner's sentences, and
`Watcher.phaseLine(Context, Market)` now selects between them from the relay's
own `market_state.phase`:

```java
static String phaseLine(Context c, Market market) {
    if (market == null || !market.phaseKnown()) {
        return c.getString(R.string.market_status_unreported);
    }
    String phase = market.phase;
    if ("OPEN".equals(phase) || "WARMUP".equals(phase)) {
        return "";
    }
    if ("BREAK".equals(phase)) {
        return market.nextEvent.isEmpty()
                ? c.getString(R.string.market_on_break)
                : c.getString(R.string.market_break_resumes, market.nextEvent);
    }
    return c.getString(R.string.market_closed_now);
}
```

The mapping is deliberate:

| relay phase | app sentence |
|---|---|
| `BREAK` | Market is on a break right now (trading resumes 14:32 PKT). |
| `CLOSED` (weekend or PSX holiday) | Market is closed now. |
| `POST_CLOSE` | Market is closed now. |
| `PRE_OPEN` | Market is closed now. |
| `OPEN` / `WARMUP` | nothing: the pill already reads ONLINE |
| phase not reported | Market status not reported by the relay yet. |

Two judgement calls, flagged rather than buried:

1. **The last row is not the owner's wording.** An absent phase used to read
   `PSX session closed.`, which is the string being retired, but replacing it
   with "Market is closed now." would assert a session the relay never
   confirmed. SO-3 forbids inventing data, and a wrong "closed" on a live
   session is the single most damaging thing this card can say. So an unknown
   phase says it is unknown. Once the relay is deployed this row should never
   appear.
2. **The weekend and holiday nuance was folded away.** The previous code said
   "Weekend: the exchange is closed" and "PSX holiday: no session today". The
   owner asked for one closed sentence, so those read "Market is closed now."
   The distinction is easy to restore from `market.tradingDay` if it is missed.

### 3.2 Glyphs and accessibility

Glyphs and labels are now resources, so the text and its spoken description
cannot drift apart, and the pill announces itself:

```xml
<string name="status_online">"✓  ONLINE"</string>
<string name="cd_status_online">System status: online. The market is open and the quant is running.</string>
```

```java
statusPill.setText(getString(online
        ? R.string.status_online : R.string.status_offline));
statusPill.setContentDescription(getString(online
        ? R.string.cd_status_online : R.string.cd_status_offline));
```

`activity_main.xml` also gains `android:accessibilityLiveRegion="polite"` on the
pill, which is the Material answer for a state indicator that changes on its
own, and the layout now seeds from `@string/status_checking`.

**A trap worth knowing about.** The strings are quoted on purpose. `aapt2`
collapses runs of whitespace in resource values, so an unquoted
`✓  ONLINE` (two spaces) is stored as `✓ ONLINE` (one space). This was caught by
inspecting `resources.arsc` in the built APK, not by reading the source, and
fixed by quoting the value.

I then swept **every** string resource for the same defect, and exactly one is
affected:

```
COLLAPSED market_waiting: 'KSE100  \u00b7  loading' -> 'KSE100 \u00b7 loading'
strings that will lose spacing: 1
```

That is pre-existing, not something this change introduced, and it is the only
one left. I did not touch it because it is outside this request; quoting it is a
one line fix if the loading state should keep its wide spacing.

### 3.3 Strict typing for the financial values

The old model used sentinels: `double price = Double.NaN`, `long volume = -1L`.
A sentinel *looks like a value* to the compiler, so an unknown price flows into
arithmetic and prints as a number. The fields are now boxed and nullable, and a
single gate enforces numeric hygiene:

```java
private static Double numberOrNull(JSONObject row, String key) {
    if (row == null || row.isNull(key)) {
        return null;
    }
    double value = row.optDouble(key, Double.NaN);
    return (Double.isNaN(value) || Double.isInfinite(value)) ? null : value;
}
```

```java
static final class Leader {
    String symbol = "";
    Double price;      // null: the relay reported no price
    Double changePct;  // null: no day's movement
    Long volume;       // null: no volume
    Long buy;          // null: no genuine split
    Long sell;
    boolean hasSplit() { return buy != null && sell != null; }
    boolean hasVolume() { return volume != null; }
}
```

Read sites now have to handle the unknown case, which is where the crash and
the fake zero used to live:

```java
if (row.hasSplit()) {
    sb.append(String.format(Locale.US, "   B=%,d  S=%,d  T=%,d",
            row.buy, row.sell, row.volume));
} else if (row.hasVolume()) {
    sb.append(String.format(Locale.US, "   T=%,d", row.volume));
}
if (row.price != null) {
    sb.append(String.format(Locale.US, "   Rs %,.2f", row.price));
}
```

`Market.hasIndex()` likewise requires all three index numbers, so a
half-reported index renders as "loading" rather than as a zero, and the
unboxing in `renderMarket` cannot throw.

### 3.4 Robust error handling for a feed spike

The old reader appended `readLine()` in an unbounded loop, so one oversized or
truncated response could exhaust the heap and kill the app. Reads are now
bounded, with a distinguished failure path:

```java
private static final int MAX_BODY_CHARS = 512 * 1024;

private static String readBounded(InputStream stream) throws IOException {
    StringBuilder sb = new StringBuilder(4096);
    char[] buffer = new char[8192];
    try (BufferedReader reader = new BufferedReader(
            new InputStreamReader(stream, StandardCharsets.UTF_8))) {
        int read;
        while ((read = reader.read(buffer)) != -1) {
            if (sb.length() + read > MAX_BODY_CHARS) {
                throw new PayloadTooLarge();
            }
            sb.append(buffer, 0, read);
        }
    }
    return sb.toString();
}
```

```java
} catch (PayloadTooLarge spike) {
    market.note = c.getString(R.string.market_payload_too_large);
} catch (Exception e) {
    market.note = c.getString(R.string.market_card_failed,
            e.getClass().getSimpleName());
}
```

Also fixed: `getErrorStream()` can be null, which the old code dereferenced.
It now throws with the HTTP code instead of a NullPointerException. A
malformed body still empties the card and never crashes the app.

## 4. Integration

Everything is already in place in the tree; no wiring is required. To rebuild
and install, using the project's own no-Gradle pipeline:

```bash
TOOLS=/c/Users/rehan/android-tools
JDK=$(ls -d $TOOLS/jdk-* | head -1); PLAT=$TOOLS/android-11/android.jar; B=android/app/build
"$TOOLS/aapt2x/aapt2.exe" compile --dir android/app/src/main/res -o "$B/res.zip"
"$TOOLS/aapt2x/aapt2.exe" link -o "$B/app.unaligned.apk" -I "$PLAT" \
  --manifest android/app/src/main/AndroidManifest.xml --java "$B/gen" --auto-add-overlay "$B/res.zip"
find android/app/src/main/java "$B/gen" -name "*.java" > "$B/sources.txt"
"$JDK/bin/javac" -encoding UTF-8 -source 8 -target 8 -classpath "$PLAT" -d "$B/classes" @"$B/sources.txt"
"$JDK/bin/java" -cp "$TOOLS/r8.jar" com.android.tools.r8.D8 --release --lib "$PLAT" --output "$B/dex" $(find "$B/classes" -name "*.class")
python - <<'PY'
import zipfile, shutil
B = "android/app/build"
shutil.copy(f"{B}/app.unaligned.apk", f"{B}/app.apk")
with zipfile.ZipFile(f"{B}/app.apk", "a", zipfile.ZIP_DEFLATED) as z:
    z.write(f"{B}/dex/classes.dex", "classes.dex")
PY
"$JDK/bin/java" -jar "$TOOLS/uber-apk-signer.jar" -a "$B/app.apk" --out "$B/signed"
```

The signed artifact is `android/app/build/signed/app-aligned-debugSigned.apk`.
I did not copy it to the Desktop or install it, since that is the owner's step.

**The step that actually delivers items 2, 3 and 4 is deploying the relay**,
because the app cannot render fields the relay does not send. That is
`python cloud/pair.py deploy` (SO-5: it reads the Cloudflare token from the
environment and binds the secrets). I did not run it, as deploying is the
owner's call.

## 5. Why item 4 cannot be finished from the edge

The exchange's constituent table carries **one** volume column, so no amount of
parsing can split it into buy and sell. `cloud/worker.js` therefore returns
`buy_volume: null` with an honest reason, and `src/data/market_snapshot.py`
fills the split from `src/data/tick_volume.py`, which reads the broker tick
capture. That capture only exists while a live session is running on the PC.
So:

* the app is already correct (it shows `B=`/`S=` as soon as a real split
  arrives, and shows `T=` alone with a stated reason otherwise);
* the split will appear only when the PC is pushing a snapshot during a live
  session and the tick capture for that session exists.

Today is a Saturday, so there is no live session and nothing to capture. This
is a data availability limit, not a code gap.

## 6. Verification log

| check | command | result |
|---|---|---|
| Live relay `/health` | `GET /health` | HTTP 200, no `market_state` |
| Live relay `/market` | `GET /market` | HTTP 200, leaders lack `change_pct`, `buy_volume`, `sell_volume` |
| Resources parse | `xml.etree.ElementTree` on layout and strings | both parse |
| Every string reference resolves | scan of `@string/` and `R.string.` against `strings.xml` | 31 references, 0 missing |
| aapt2 compile | `aapt2 compile --dir .../res` | exit 0 |
| aapt2 link | `aapt2 link ... --auto-add-overlay` | exit 0 |
| javac type check | `javac -source 8 -target 8 -classpath android.jar` | exit 0, only the bootclasspath warning |
| D8 | `com.android.tools.r8.D8 --release` | exit 0, `classes.dex` 29,528 bytes |
| signing | `uber-apk-signer.jar` | zipalign verified, signature verified [v2, v3], 0 errors |
| APK identity | `aapt2 dump badging` | `pk.quantofrehan`, versionCode 14, versionName 1.6.0 |
| New copy in the APK | search `resources.arsc` | "Market is closed now.", "Market is on a break right now.", "Market status not reported by the relay yet.", and the online accessibility sentence all present |
| Glyph spacing preserved | search `resources.arsc` for the two-space form | present for all three pill strings |
| Retired string removed | search `classes.dex` | "PSX session closed." absent (moved out of code into resources) |

## 7. Limitations, stated plainly

1. **Not rendered on a device.** The APK builds and its resources are verified
   byte for byte, but I have no emulator or phone here, so the visual result is
   unverified. The layout change is additive and the glyphs are unchanged
   codepoints, which limits the risk but does not remove it.
2. **No live session was exercised.** It is Saturday, so the closed and break
   sentence paths could not be observed against real data. The mapping is
   verified by reading `market_state.phase`, not by watching it fire.
3. **The relay was not deployed and the APK was not installed.** Both are the
   owner's steps. Until the relay is deployed, items 2, 3 and 4 will still look
   exactly like the screenshot on the phone.
4. **`android.provider.Settings` and notification strings remain hardcoded**
   ("Token saved.", "Watchdog armed.") because they are outside this request.
   The one user-facing relay string I left inline is
   "The relay answered but reported a fault."
