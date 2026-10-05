"""
One-shot live probe: broker feed integration feasibility (2026-09-25).

READ-ONLY. No login, no session, no order endpoints - the feed socket and
the public read tier only. Run during market hours.
ASCII-only output (Windows console).
"""
import socket
import sys
import time

sys.path.insert(0, r"C:\Users\rehan\OneDrive\Desktop\PSX-KMIALL-Bot\eclear_recon")
import eclient  # noqa: E402

HOSTS = ["nxg1.eclear.com.pk", "nxg2.eclear.com.pk", "nxg.eclear.com.pk"]
PORT = 8484
# Owner's own holdings first (known MTM values to validate decode), then
# liquid names for good measure.
SYMS = "OGDC;ILP;PRL;SNGP;FFC;PPL;TOMCL;UNITY;BECO;LUCK;MARI;SYS;HBL;"
HOLDINGS = {"PRL": 91.98, "SNGP": 91.98, "FFC": 540.95, "PPL": 231.50,
            "ILP": 98.80, "TOMCL": 33.47, "UNITY": 8.05, "BECO": 4.40}


def socket_probe(seconds: int = 30) -> None:
    print("=" * 70)
    print("SOCKET PROBE: MKT-FEED subscription, no auth")
    print("=" * 70)
    for host in HOSTS:
        try:
            sock = socket.create_connection((host, PORT), timeout=8)
        except OSError as exc:
            print(f"{host}: connect FAILED {exc}")
            continue
        print(f"{host}: connected")
        sock.settimeout(3)
        buf = b""
        messages: list[str] = []
        ticks: dict[str, str] = {}
        exs: list[str] = []
        try:
            banner = sock.recv(4096)
            print(f"banner: {banner[:60]!r}")
            sock.sendall(f"MKT-FEED|{SYMS}%".encode())
            deadline = time.time() + seconds
            last_beat = time.time()
            while time.time() < deadline:
                try:
                    chunk = sock.recv(65536)
                    if chunk:
                        buf += chunk
                except socket.timeout:
                    pass
                except OSError:
                    break
                if time.time() - last_beat >= 5:
                    try:
                        sock.sendall(b"HELLO|%")
                    except OSError:
                        break
                    last_beat = time.time()
                while b"%" in buf:
                    raw, buf = buf.split(b"%", 1)
                    text = raw.decode("utf-8", "replace").strip()
                    if not text:
                        continue
                    messages.append(text)
                    if text.startswith("MKT-FEED"):
                        for row in text.split("*", 1)[1].split("$"):
                            if ";" in row:
                                ticks.setdefault(row.split(";")[0], row)
                    elif text.startswith("EXS-FEED"):
                        exs.append(text)
            sock.close()
        except OSError as exc:
            print(f"socket error: {exc}")
            try:
                sock.close()
            except OSError:
                pass

        print(f"total messages : {len(messages)}")
        kinds: dict[str, int] = {}
        for m in messages:
            kind = m.split("*", 1)[0].split("|", 1)[0]
            kinds[kind] = kinds.get(kind, 0) + 1
        print(f"message kinds  : {kinds}")
        print(f"symbols seen   : {len(ticks)} -> {sorted(ticks)}")
        if exs:
            print(f"EXS sample     : {exs[0][:200]}")
        # Raw message samples for field-map decoding.
        mkt = [m for m in messages if m.startswith("MKT-FEED")]
        for sample in mkt[:3]:
            print(f"RAW MKT: {sample[:300]}")
        for sample in messages[:3]:
            print(f"RAW    : {sample[:200]}")
        # Validate holdings decode against the 14:35 MTM snapshot.
        if ticks:
            print("HOLDING VALIDATION (broker MTM at 14:35 vs live tick):")
            for sym, known in HOLDINGS.items():
                row = ticks.get(sym)
                if not row:
                    print(f"  {sym:6s}: (no tick)")
                    continue
                f = row.split(";")
                print(f"  {sym:6s}: last={f[2] if len(f) > 2 else '?'} "
                      f"bid={f[3] if len(f) > 3 else '?'} "
                      f"ask={f[6] if len(f) > 6 else '?'} "
                      f"(MTM 14:35 was {known})")
            print("RAW ROW FIELDS (one holding, every index):")
            for sym in HOLDINGS:
                if sym in ticks:
                    for i, val in enumerate(ticks[sym].split(";")):
                        print(f"  [{i:2d}] {val}")
                    break
        return
    print("ALL FEED HOSTS UNREACHABLE")


def http_probes() -> None:
    print("=" * 70)
    print("HTTP PROBES (public read tier, no session)")
    print("=" * 70)
    probes = [
        ("ScripServlet full reload",
         "https://nxg2.eclear.com.pk/pero/ScripServlet"
         "?ScripLoadDateTime=0&IsReLoad=1"),
        ("GetSymbolsViaIndex KMIALLSHR",
         "https://nxg2.eclear.com.pk/pero/GetSymbolsViaIndex"
         "?index=KMIALLSHR&sessionID="),
        ("singlefeed empty-session",
         "https://nxg2.eclear.com.pk/pero/singlefeed"
         "?FromActivity=HomeFragment&SESSION_ID=&symbollist=OGDC;ILP;&abc=1"),
        ("GetSingleFeedWithMarketCap empty-session",
         "https://nxg2.eclear.com.pk/pero/GetSingleFeedWithMarketCap"
         "?FromActivity=HomeFragment&SESSION_ID=&symbollist=OGDC;ILP;&abc=1"),
        ("TopMoversServlet",
         "https://nxg2.eclear.com.pk/pero/TopMoversServlet"),
        ("GetOHLCData OGDC 5m (vt host)",
         "https://vt.eclear.com.pk/pero/GetOHLCData"
         "?scrip=OGDC&market=REG&check=symbol&interval=5"),
    ]
    for name, url in probes:
        status, text = eclient.http_get(url)
        head = text[:500].encode("ascii", "replace").decode("ascii")
        print(f"\n--- {name}: HTTP {status}, {len(text):,} chars")
        print(head)
    print("\nDONE")


if __name__ == "__main__":
    socket_probe(seconds=int(sys.argv[1]) if len(sys.argv) > 1 else 30)
    http_probes()
