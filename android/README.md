# android/ : Quant of Rehan companion app

A small, logo-branded Android app for the owner's phone. It answers two
questions at a glance: is the system working, and what are the latest
signals. Signal-only by construction (SO-1): the app talks only to the
Cloudflare relay, never to Telegram, never to a broker.

## What it shows

- A live status card: ONLINE when the relay (and behind it, the whole
  pipeline) answers, with the relay's Karachi clock and next schedule event.
- A signals panel fed by the relay's `/signals` feed (admin token required,
  stored once in the app).
- Phone notifications on status changes and new signals, checked every 15
  minutes by a watchdog that re-arms itself and survives phone restarts.

## Branding

Colors come straight from `assets/quant_of_rehan_logo.svg`: deep purple
background (#0B070D, #170D1C), gold frame (#D9A441, #F8CE66), ascending
green candles (#2FAE6F), teal accents (#4A9C95). The launcher icon is the
logo; the status-bar icon is a white gold-diamond-and-candles glyph.

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
  /c/Users/rehan/OneDrive/Desktop/QuantOfRehan-v1.2.0.apk
```

The APK is signed with the local debug key (v2+v3), which is enough for
direct installation on the owner's phone. Install: copy the APK to the
phone (or open the OneDrive app), allow install-from-unknown-apps for the
source, install, open, paste the relay admin token from .env, arm the
watchdog, and allow notifications.
