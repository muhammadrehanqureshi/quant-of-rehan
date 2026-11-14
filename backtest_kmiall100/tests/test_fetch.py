"""The data downloader: refuses unsafe archives and unsafe links."""

import importlib.util
import io
import tarfile
import urllib.request
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fetch_data", ROOT / "tools" / "fetch_data.py")
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)


def test_http_is_refused(tmp_path):
    with pytest.raises(SystemExit):
        F.download("http://example.com/x.zip", "", tmp_path / "x")


def test_zip_slip_is_refused(tmp_path):
    p = tmp_path / "evil.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("../../escape.csv", "a,b\n1,2\n")
    with zipfile.ZipFile(p) as z, pytest.raises(SystemExit):
        F.safe_extract_zip(z, tmp_path / "out")
    assert not (tmp_path / "escape.csv").exists()


def test_tar_link_and_traversal_are_refused(tmp_path):
    p = tmp_path / "evil.tar"
    with tarfile.open(p, "w") as t:
        info = tarfile.TarInfo("5m/link.csv")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        t.addfile(info)
    with tarfile.open(p) as t, pytest.raises(SystemExit):
        F.safe_extract_tar(t, tmp_path / "out")
    p2 = tmp_path / "evil2.tar"
    with tarfile.open(p2, "w") as t:
        data = b"x"
        info = tarfile.TarInfo("../up.csv")
        info.size = 1
        t.addfile(info, io.BytesIO(data))
    with tarfile.open(p2) as t, pytest.raises(SystemExit):
        F.safe_extract_tar(t, tmp_path / "out2")


def test_good_zip_unpacks(tmp_path):
    p = tmp_path / "ok.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("5m/AAA.csv", "time,open,high,low,close,volume\n")
        z.writestr("1d/AAA.csv", "time,open,high,low,close,volume\n")
    assert F.unpack(p, tmp_path / "data", "ok.zip") == 2
    assert (tmp_path / "data" / "5m" / "AAA.csv").exists()


def test_token_is_dropped_on_a_redirect_to_another_host():
    h = F.NoAuthOnForeignRedirect()
    req = urllib.request.Request("https://api.github.com/a", headers={"Authorization": "Bearer secret"})
    new = h.redirect_request(req, None, 302, "Found", {}, "https://objects.example.com/b?sig=1")
    assert "Authorization" not in {k.title() for k in new.headers} and "Authorization" not in new.unredirected_hdrs
    same = h.redirect_request(req, None, 302, "Found", {}, "https://api.github.com/b")
    assert "Authorization" in {k.title() for k in same.headers}


def test_redirect_to_plain_http_is_refused():
    h = F.NoAuthOnForeignRedirect()
    req = urllib.request.Request("https://api.github.com/a")
    with pytest.raises(Exception):
        h.redirect_request(req, None, 302, "Found", {}, "http://evil.example.com/b")
