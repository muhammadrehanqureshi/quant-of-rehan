"""Cloud KMIALL intraday scanner.

Production signal path. It preserves every genuine 1-minute bar through the
decision engine, evaluates causal 5-minute structure, and delivers at most
one BUY per Karachi session. No broker order is placed here.
"""
from __future__ import annotations
import argparse, json, sys
from datetime import datetime, time, timedelta
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.data.sessions import is_market_open, now_karachi
from src.signals.intraday_engine import choose, validate_signal
from src.signals.signal_push import load_relay_url, post_json, read_admin_token

MIN_COVERAGE=0.80
MAX_BAR_AGE_MINUTES=10

def aggregate_minute_bars(path:Path,symbols:list[str],session_day:str,as_of:datetime)->pd.DataFrame:
    allowed=set(symbols)
    rows=[]
    if not path.is_file():
        return pd.DataFrame(columns=["symbol","date","open","high","low","close","bar_time"])
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record=json.loads(line)
            symbol=str(record["symbol"]).strip()
            if symbol not in allowed: continue
            captured=datetime.fromisoformat(record["ts"])
            if captured.date().isoformat()!=session_day: continue
            for bar in record.get("bars",[]):
                minute=datetime.combine(captured.date(),time.fromisoformat(str(bar["t"])),
                                        tzinfo=as_of.tzinfo)
                if minute>as_of: continue
                vals={k:float(bar[k]) for k in ("o","h","l","c")}
                if min(vals.values())<=0: continue
                rows.append({"symbol":symbol,"date":pd.Timestamp(session_day),
                             "open":vals["o"],"high":vals["h"],"low":vals["l"],
                             "close":vals["c"],"bar_time":minute})
        except (KeyError,TypeError,ValueError,json.JSONDecodeError):
            continue
    if not rows: return pd.DataFrame(columns=["symbol","date","open","high","low","close","bar_time"])
    out=pd.DataFrame(rows).drop_duplicates(["symbol","bar_time"]).sort_values(["symbol","bar_time"])
    latest=out.groupby("symbol")["bar_time"].max()
    fresh=set(latest[latest.apply(lambda x:as_of-x<=timedelta(minutes=MAX_BAR_AGE_MINUTES))].index)
    return out[out["symbol"].isin(fresh)].reset_index(drop=True)

def build_history(session_day:str)->pd.DataFrame:
    from scripts.signal_daily import WINDOW_KMI,fetch_window,filter_to_universe
    fetch_window(datetime.fromisoformat(session_day).date()-timedelta(days=1))
    filter_to_universe()
    h=pd.read_csv(WINDOW_KMI,parse_dates=["date"])
    return h[h["date"].dt.date.astype(str)<session_day].copy()

def deliver_once(signal,scan_time:datetime)->bool:
    validate_signal(signal)
    token=read_admin_token(); relay_url=load_relay_url()
    import requests
    try:
        r=requests.get(relay_url+"/signals",headers={"x-admin-token":token},timeout=15)
        r.raise_for_status(); stored=str(r.json().get("signals",""))
    except Exception as exc:
        raise RuntimeError(f"relay state check failed: {exc}") from exc
    if "INTRADAY BUY " in stored and signal.session_day in stored:
        print("An intraday signal already exists for this session; no repeat.")
        return False
    text=(f"INTRADAY BUY {signal.symbol} {signal.session_day} (Karachi)\n"
          f"Entry reference: {signal.entry_price:.4f} @ {signal.bar_time} PKT\n"
          f"TP: {signal.target_price:.4f} (+2.00% from entry reference)\n"
          f"Score: {signal.score:.2f} | KMIALL breadth: {signal.market_breadth:.0%}\n"
          f"Day: {signal.day_change_pct:+.2f}% | RS: {signal.relative_strength_pct:+.2f}%\n"
          f"Structure: sweep={'Y' if signal.swept_low else 'N'}, "
          f"displacement={'Y' if signal.displacement else 'N'}, "
          f"FVG-retrace={'Y' if signal.fvg_retrace else 'N'}\n"
          "Signal only. No broker order was placed.")
    post_json(relay_url,"/signals",{"signals":text},token)
    post_json(relay_url,"/notify",{"text":text,"kind":"signals"},token)
    return True

def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser()
    p.add_argument("--bars",type=Path); p.add_argument("--history",type=Path)
    args=p.parse_args()
    now=now_karachi()
    if not is_market_open(now):
        print(f"SKIPPED: market closed at {now:%H:%M} PKT"); return 0
    session_day=now.date().isoformat()
    from src.data.feed_capture import load_universe
    from scripts.signal_daily import UNIVERSE_FALLBACK,UNIVERSE_LEGACY
    upath=UNIVERSE_LEGACY if UNIVERSE_LEGACY.is_file() else UNIVERSE_FALLBACK
    symbols=load_universe(upath)
    bars_path=args.bars or ROOT/"data"/"feed_capture"/f"ohlc_{now:%Y%m%d}.ndjson"
    partial=aggregate_minute_bars(bars_path,symbols,session_day,now)
    coverage=partial["symbol"].nunique()/max(len(symbols),1)
    print(f"Scan {session_day} {now:%H:%M} PKT: {partial['symbol'].nunique()}/{len(symbols)} symbols ({coverage:.1%})")
    if coverage<MIN_COVERAGE:
        print("NO TRADE: insufficient current-session KMIALL coverage"); return 0
    history=(pd.read_csv(args.history,parse_dates=["date"])
             if args.history else build_history(session_day))
    signal,reason=choose(partial,history,len(symbols),session_day)
    if signal is None:
        print(f"NO TRADE: {reason}"); return 0
    print(signal.line())
    try: sent=deliver_once(signal,now)
    except Exception as exc:
        print(f"DELIVERY FAILED: {type(exc).__name__}: {exc}"); return 1
    print("Delivered to APK and Telegram." if sent else "Already delivered for today.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
