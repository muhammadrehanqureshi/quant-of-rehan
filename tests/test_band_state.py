"""Band state survives a GitHub runner: restore, push, prune, skip gracefully.

The R2 API is faked, so no test phones home, and the day's files live in a
temporary directory instead of the repo's data/.
"""

from __future__ import annotations

import gzip
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from urllib.parse import unquote
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data import band_state  # noqa: E402

TODAY = date(2026, 10, 15)


def _resp(status: int = 200, json_body=None, content: bytes = b""):
    class R:
        status_code = status
        text = ""

        def json(self):
            return json_body if json_body is not None else {"success": bool(status < 300)}

    R.content = content
    return R()


class _CallR2:
    """R2 object storage for _call-level fakes: keyed by the object key."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def call(self, method, url, *, headers, data=None, params=None, timeout=None):
        key = unquote(url.split("/objects/", 1)[1].rsplit("?", 1)[0])
        if method == "PUT":
            self.objects[key] = data or b""
            return {"ok": True, "status": 200, "body": b""}
        if method == "GET":
            body = self.objects.get(key)
            if body is None:
                return {"ok": False, "status": 404, "body": b""}
            return {"ok": True, "status": 200, "body": body}
        raise AssertionError(f"unexpected method {method}")


class BandStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)
        self.capture = self.tmp / "capture.ndjson"
        self.state = self.tmp / "session_state.json"
        self.paths = [
            (f"day={TODAY.isoformat()}/capture.ndjson.gz", self.capture),
            (f"day={TODAY.isoformat()}/session_state.json", self.state),
        ]
        self.call_r2 = _CallR2()
        self._patches = [
            patch("src.data.band_state._credential", return_value=("tok", "acct")),
            patch("src.data.band_state.bucket_url",
                  return_value="https://fake/api(acct)/buckets/b/objects"),
            patch("src.data.band_state._call", self.call_r2.call),
            patch("src.data.band_state.state_paths", return_value=self.paths),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    # reset the fixture between tests
    def _reset_paths(self, *paths: tuple[str, Path]) -> None:
        self.paths[:] = paths

    def test_roundtrip_tape_survives_a_local_delete(self):
        self.capture.write_bytes(b"raw tape lines\n" * 1000)
        self.assertTrue(band_state.push(TODAY)["ok"])
        self.assertTrue(band_state.push(TODAY)["ok"])
        self.assertTrue(self.capture.stat().st_size > 0)
        self.capture.unlink()
        restored = band_state.restore(TODAY)
        self.assertIn("capture.ndjson", restored["restored"], restored)
        self.assertEqual(self.capture.read_bytes(), b"raw tape lines\n" * 1000,
                         "decompressed tape differs from what was pushed")

    def test_push_uploads_the_tape_gzipped(self):
        self.capture.write_bytes(b"x" * 10000)
        band_state.push(TODAY)
        stored = self.call_r2.objects[f"day={TODAY.isoformat()}/capture.ndjson.gz"]
        self.assertEqual(gzip.decompress(stored), b"x" * 10000)
        self.assertLess(len(stored), 10000)

    def test_restore_never_overwrites_a_local_file_with_older_remote(self):
        stored_tape = gzip.compress(b"stale-earlier-tape")
        self.call_r2.objects[f"day={TODAY.isoformat()}/capture.ndjson.gz"] = stored_tape
        # The local machine already holds a newer tape: band 2 resumed after
        # a crash and appended, so a restore must not roll it backwards.
        self.capture.write_bytes(b"newer-local-tape")
        self.state.write_text('{"day": "2026-10-15", "n": 8}', encoding="utf-8")

        result = band_state.restore(TODAY)
        self.assertNotIn("capture.ndjson", result["restored"],
                         "a restore clobbered a newer local file")
        # The fresh local session state also stands; nothing is restored.
        self.assertEqual(result["restored"], [])
        self.assertEqual(self.capture.read_bytes(), b"newer-local-tape")
        self.assertEqual(self.state.read_text(encoding="utf-8"),
                         '{"day": "2026-10-15", "n": 8}')

    def test_push_with_holes_is_ok_and_the_holes_are_named(self):
        result = band_state.push(TODAY)
        self.assertTrue(result["ok"])
        self.assertIn("absent locally", result["reason"])

    def test_restore_with_nothing_on_r2_mentioned_nothing_restored(self):
        result = band_state.restore(TODAY)
        self.assertEqual(result["restored"], [])
        self.assertIn("nothing pushed yet today", result["reason"])

    def test_no_credentials_skips_cleanly(self):
        with patch("src.data.band_state._credential", return_value=None):
            self.assertEqual(
                band_state.push(TODAY),
                {"ok": False, "reason": "no CF_API_TOKEN/CF_ACCOUNT_ID credential"})
            self.assertEqual(
                band_state.restore(TODAY),
                {"ok": False, "reason": "no CF_API_TOKEN/CF_ACCOUNT_ID credential"})
        self.assertFalse(self.capture.is_file())

    def test_r2_not_enabled_is_a_named_reason_not_a_crash(self):
        class R:
            status_code = 403
            text = ""

            def json(self):
                return {"success": False, "errors": [{"code": 10042,
                        "message": "Please enable R2 through the Cloudflare Dashboard."}]}

        with patch("requests.get", return_value=R()), \
                patch("src.data.band_state.BUCKET_NAME", "quant-of-rehan-tape"):
            result = band_state.ensure_bucket()
        self.assertFalse(result["ok"])
        self.assertIn("enable", result["reason"].lower())

    def test_prune_deletes_only_objects_older_than_retention(self):
        stored = {"day=2026-09-01/capture.ndjson.gz": b"old",
                  f"day={TODAY.isoformat()}/capture.ndjson.gz": b"today"}
        with patch("src.data.band_state._credential", return_value=("t", "a")), \
                patch("band_state.RETENTION_DAYS" if False else _RET_PAT,
                      getattr(band_state, "RETENTION_DAYS")):
            pass
        # The real function; delete calls are captured.
        deletes = []

        class R2:
            status_code = 200

            def json(self):
                return {"success": True, "result": {"objects": [
                    {"key": k} for k in stored]}}

        def fake_get(url, headers=None, params=None, timeout=None):
            return R2()

        def fake_delete(url, headers=None, timeout=None):
            deletes.append(unquote(url.split("/objects/", 1)[1]))

            class R:
                status_code = 200

            return R()

        with patch("requests.get", fake_get), patch("requests.delete", fake_delete):
            band_state.prune(days=1, creds=("t", "a"))
        self.assertEqual(deletes, ["day=2026-09-01/capture.ndjson.gz"],
                         "today's object must survive; the past must not")


_RET_PAT = "src.data.band_state.RETENTION_DAYS"

_test_roundtrip = None  # no legacy names below this line


class PushRestoreEndToEnd(unittest.TestCase):
    """Both directions through the same single faked R2."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)
        self.capture = self.tmp / "capture.ndjson"
        self.paths = [(f"day={TODAY.isoformat()}/capture.ndjson.gz", self.capture)]
        self.call_r2 = _CallR2()
        for p in [patch("src.data.band_state._credential", return_value=("t", "a")),
                  patch("src.data.band_state.bucket_url",
                        return_value="https://fake/objects"),
                  patch("src.data.band_state._call", self.call_r2.call),
                  patch("src.data.band_state.state_paths", return_value=self.paths)]:
            p.start()
            self.addCleanup(p.stop)

    def test_push_then_fresh_restore_recovers_the_tape(self):
        self.capture.write_bytes(b"a tape line with ONE trade\n" * 500)
        band_state.push(TODAY)
        self.capture.unlink()
        result = band_state.restore(TODAY)
        self.assertIn("capture.ndjson", result["restored"])
        self.assertTrue(self.capture.is_file())


if __name__ == "__main__":
    unittest.main()
