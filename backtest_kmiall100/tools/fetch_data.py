#!/usr/bin/env python3
"""Download the data bundle inside the cloud job. Never runs on your PC.

Environment (set as GitHub Actions secrets):
  DATA_URL     https link to one file: a .zip, a .tar.gz, or a single .csv/.csv.gz/.parquet
  DATA_TOKEN   optional. Sent as a Bearer token, for a private GitHub release asset
               (use the API asset URL) and dropped again if the download is redirected to another host
  DATA_SHA256  optional. Expected SHA-256 of the file, the download is refused when it does not match

Safety: https only, size cap, archive members may not escape the target folder
(zip slip), no links inside archives, no more than 20,000 files, and the URL
(which can carry a signature) is never printed, only the host name.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlparse

MAX_DOWNLOAD = int(os.environ.get("MAX_BYTES", str(3 * 1024 ** 3)))
MAX_UNPACKED = 12 * 1024 ** 3
MAX_FILES = 20000
OK_SUFFIX = (".csv", ".csv.gz", ".parquet", ".pq")


class NoAuthOnForeignRedirect(urllib.request.HTTPRedirectHandler):
    """Keep the token on the first host only: signed storage links refuse a second credential."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            if urlparse(newurl).scheme != "https":
                raise urllib.error.URLError("refusing a redirect to a non https address")
            if urlparse(newurl).netloc != urlparse(req.full_url).netloc:
                for h in ("Authorization", "authorization"):
                    new.headers.pop(h, None)
                    new.unredirected_hdrs.pop(h, None)
        return new


def download(url: str, token: str, dest: Path) -> str:
    u = urlparse(url)
    if u.scheme != "https" or not u.netloc:
        raise SystemExit("DATA_URL must be an https address")
    headers = {"User-Agent": "kmiall100-fetch/1.0", "Accept": "application/octet-stream"}
    if token:
        headers["Authorization"] = "Bearer " + token
    opener = urllib.request.build_opener(NoAuthOnForeignRedirect())
    h = hashlib.sha256()
    n = 0
    with opener.open(urllib.request.Request(url, headers=headers), timeout=120) as r, open(dest, "wb") as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            n += len(b)
            if n > MAX_DOWNLOAD:
                raise SystemExit("download is bigger than the size cap")
            h.update(b)
            f.write(b)
    print(f"downloaded {n / 1e6:.1f} MB from {u.netloc}", flush=True)
    return h.hexdigest()


def _inside(root: Path, member: str) -> Path:
    p = (root / member).resolve()
    if os.path.commonpath([str(root.resolve()), str(p)]) != str(root.resolve()):
        raise SystemExit("archive member escapes the target folder: " + member)
    return p


def safe_extract_zip(zf: zipfile.ZipFile, root: Path) -> int:
    infos = zf.infolist()
    if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_UNPACKED:
        raise SystemExit("archive is too large or has too many files")
    n = 0
    for i in infos:
        if i.is_dir():
            continue
        if (i.external_attr >> 16) & 0o170000 == 0o120000:
            raise SystemExit("archive contains a link: " + i.filename)
        target = _inside(root, i.filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(i) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
        n += 1
    return n


def safe_extract_tar(tf: tarfile.TarFile, root: Path) -> int:
    members = tf.getmembers()
    if len(members) > MAX_FILES or sum(m.size for m in members) > MAX_UNPACKED:
        raise SystemExit("archive is too large or has too many files")
    n = 0
    for m in members:
        if m.isdir():
            continue
        if not m.isreg():
            raise SystemExit("archive contains something that is not a plain file: " + m.name)
        target = _inside(root, m.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        src = tf.extractfile(m)
        with open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
        n += 1
    return n


def unpack(archive: Path, out: Path, original_name: str) -> int:
    out.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            return safe_extract_zip(z, out)
    if tarfile.is_tarfile(archive):
        with tarfile.open(archive) as t:
            return safe_extract_tar(t, out)
    name = original_name.lower()
    if name.endswith(OK_SUFFIX):
        shutil.copyfile(archive, out / Path(name).name)
        return 1
    raise SystemExit("DATA_URL is not a zip, a tar archive or a csv or parquet file")


def main() -> int:
    url = os.environ.get("DATA_URL", "").strip()
    if not url:
        print("DATA_URL is not set. Add it as a repository secret, see the README.", file=sys.stderr)
        return 2
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
    want = os.environ.get("DATA_SHA256", "").strip().lower()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "bundle"
        got = download(url, os.environ.get("DATA_TOKEN", "").strip(), tmp)
        if want and got != want:
            print("checksum mismatch, refusing to use the download", file=sys.stderr)
            return 4
        n = unpack(tmp, out, Path(urlparse(url).path).name)
    files = [p for p in out.rglob("*") if p.is_file()]
    print(f"unpacked {n} files, {len(files)} under {out}", flush=True)
    if not files:
        print("no data files after unpacking", file=sys.stderr)
        return 5
    return 0


if __name__ == "__main__":
    sys.exit(main())
