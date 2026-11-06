#!/usr/bin/env python3
"""Measure how often the relay's /quotes answer really changes.

Runs on any machine with Python 3.8+ and no packages. It asks /quotes once a
second for N seconds (default 120, at most 900) and prints, in plain words:

  * how old the freshest stock is, second by second, and how that ages and
    drops back (the "beat" of the feed),
  * how long each stock takes to show a new tick (its own repeat time),
  * whether the whole feed ever went quiet (a stall),
  * how long each request took.

Use it from a GitHub Actions runner to separate "the relay is slow" from "this
PC's network is slow": if the runner sees the same beat as the PC, the lag is
upstream of both.

    python3 scripts/feed_cadence_probe.py --seconds 180
    python3 scripts/feed_cadence_probe.py --relay http://127.0.0.1:8787 --seconds 20

It only issues GET /quotes, about 1 request per second, and writes nothing
except an optional --out file. No token, no header other than a plain
User-Agent.
"""
import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request

DEFAULT_RELAY = "https://quant-of-rehan-relay.mrmrehanqureshi.workers.dev"


def fetch(relay, timeout):
    req = urllib.request.Request(relay.rstrip("/") + "/quotes",
                                 headers={"User-Agent": "QoR-feed-probe/1"})
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read(8 << 20)
    rtt = time.monotonic() - t0
    return json.loads(body.decode("utf-8", "replace")), rtt


def pct(values, p):
    if not values:
        return None
    v = sorted(values)
    k = min(len(v) - 1, max(0, int(round((p / 100) * (len(v) - 1)))))
    return v[k]


def run(relay, seconds, out):
    last_obs, last_change = {}, {}
    repeats, freshest, rtts, fails = [], [], [], 0
    stall, longest_stall = 0, 0
    beat_drops = []  # seconds the freshest age reached just before it dropped back
    prev_fresh = None
    start = time.monotonic()
    lines = []
    for i in range(seconds):
        tick = start + i
        wait = tick - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        now = time.monotonic()
        try:
            o, rtt = fetch(relay, 4)
            if not o.get("ok"):
                raise ValueError("ok=false")
        except (urllib.error.URLError, OSError, ValueError) as e:
            fails += 1
            lines.append("%3ds  FAIL %s" % (i, e))
            continue
        rtts.append(rtt)
        ages, changed = [], 0
        for q in o.get("quotes", []):
            sym, obs = q.get("symbol"), q.get("observed_at")
            a = q.get("age_seconds")
            if isinstance(a, (int, float)) and a >= 0:
                ages.append(a)
            if not sym or not obs:
                continue
            if sym in last_obs and last_obs[sym] != obs:
                changed += 1
                if sym in last_change:
                    repeats.append(now - last_change[sym])
                last_change[sym] = now
            elif sym not in last_obs:
                last_change.setdefault(sym, now)
            last_obs[sym] = obs
        f = min(ages) if ages else None
        if f is not None:
            freshest.append(f)
            if prev_fresh is not None and f + 1 < prev_fresh:
                beat_drops.append(prev_fresh)
            prev_fresh = f
        stall = stall + 1 if changed == 0 else 0
        longest_stall = max(longest_stall, stall)
        lines.append("%3ds  freshest %s s  typical %s s  changed %3d  rtt %3d ms"
                     % (i, "-" if f is None else int(f),
                        "-" if not ages else int(statistics.median(ages)), changed, rtt * 1000))
    summary = []
    n = len(rtts)
    summary.append("answers %d of %d, failures %d" % (n, seconds, fails))
    if rtts:
        summary.append("request time: median %d ms, 95th %d ms, slowest %d ms"
                       % (statistics.median(rtts) * 1000, pct(rtts, 95) * 1000, max(rtts) * 1000))
    if freshest:
        summary.append("age of the freshest stock: median %d s, 95th %d s, worst %d s"
                       % (statistics.median(freshest), pct(freshest, 95), max(freshest)))
    if beat_drops:
        summary.append("the freshest tick aged to about %d s (median) and then dropped back, %d times: "
                       "that is a burst beat of about that many seconds" % (statistics.median(beat_drops), len(beat_drops)))
    if repeats:
        summary.append("one stock shows a new tick every %d s (median), %d s (95th), over %d changes"
                       % (statistics.median(repeats), pct(repeats, 95), len(repeats)))
    summary.append("longest stretch with no stock changing at all: %d s" % longest_stall)
    verdict = decide(fails, n, rtts, freshest, repeats, longest_stall, beat_drops)
    summary.append("VERDICT: " + verdict)
    text = "\n".join(lines + [""] + summary)
    print(text)
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return verdict


def decide(fails, n, rtts, freshest, repeats, longest_stall, beat_drops):
    if n == 0:
        return "NETWORK: no answer at all"
    if fails > n * 0.1 or (rtts and pct(rtts, 95) > 2.5):
        return "NETWORK: answers fail or crawl between here and the relay"
    if longest_stall >= 20 and not beat_drops:
        return "STALL: the whole feed went quiet for %d s, which is upstream of the reader" % longest_stall
    if beat_drops and statistics.median(beat_drops) >= 12:
        return ("BURSTS: the whole feed refreshes together about every %d s, so every reader sees the same "
                "lag. The data is as new as the relay's snapshot, and only a faster upstream changes it"
                % statistics.median(beat_drops))
    if repeats and statistics.median(repeats) >= 12:
        return "WIRE: each stock repeats only about every %d s" % statistics.median(repeats)
    return "CLEAN: stocks refresh every few seconds and nothing stalled"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--relay", default=DEFAULT_RELAY)
    ap.add_argument("--seconds", type=int, default=120)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if not a.relay.startswith(("http://", "https://")):
        sys.exit("the relay must be an http or https address")
    run(a.relay, max(10, min(900, a.seconds)), a.out)
