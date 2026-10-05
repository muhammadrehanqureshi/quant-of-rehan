"""Deliver the built viewer APK to the owner's Telegram (v4.2.1).

The artifact alone is not delivery - the owner asked for the app on
his phone. The bot already talks to him on Telegram, so the built APK
rides the SAME channel as a file (the bot API accepts files up to
50 MB). The .apk filename makes Telegram offer it as an installable
app.

Runs inside the android-apk workflow after a successful build. Any
failure here is reported through the alert step - never a red X
(owner's zero-failure-email law).
"""
from __future__ import annotations

import os
import sys
import urllib.request
import uuid

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APK_PATH = os.path.join(
    REPO_ROOT, "android", "app", "build", "outputs", "apk", "debug",
    "app-debug.apk",
)
CAPTION = (
    "Sentinels of Rehan: tap to install. Allow 'install unknown apps' "
    "for this app when asked."
)


def main() -> int:
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        print("delivery skipped (no token/chat)")
        return 0
    if not os.path.exists(APK_PATH):
        print(f"delivery skipped (apk missing at {APK_PATH})")
        return 0

    crlf = "\r\n"
    boundary = uuid.uuid4().hex
    with open(APK_PATH, "rb") as f:
        payload = f.read()
    parts = [
        f"--{boundary}",
        'Content-Disposition: form-data; name="chat_id"',
        "",
        chat,
        f"--{boundary}",
        'Content-Disposition: form-data; name="caption"',
        "",
        CAPTION,
        f"--{boundary}",
        'Content-Disposition: form-data; name="document"; '
        'filename="Sentinels of Rehan.apk"',
        "Content-Type: application/vnd.android.package-archive",
        "",
    ]
    # The blank line between a part's headers and its content is the
    # join's trailing empty element PLUS this extra CRLF - without it
    # Telegram rejects the whole body as malformed multipart (HTTP 400,
    # 2026-10-01 first delivery attempt).
    head = crlf.join(parts).encode() + crlf.encode()
    tail = (crlf + f"--{boundary}--" + crlf).encode()
    body = head + payload + tail

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{tok}/sendDocument",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print("telegram sendDocument status:", resp.status)
            return 0
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:  # noqa: BLE001
            pass
        print(f"APK delivery FAILED: {exc} {detail}")
        return 1
    except Exception as exc:  # noqa: BLE001 - report, never red-X
        print(f"APK delivery FAILED: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
