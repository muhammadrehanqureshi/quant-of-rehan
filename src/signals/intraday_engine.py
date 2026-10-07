"""Causal KMIALL intraday signal engine.

Uses genuine captured 1-minute OHLC, converts it to causal 5-minute bars,
applies market breadth and anti-chasing vetoes, then ranks one winner.
Volume and order-flow are unavailable in this capture path and are never
fabricated.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import pandas as pd

TP_PCT=2.0
MIN_COVERAGE=0.80
MIN_HISTORY_SESSIONS=21
MIN_BARS=12
MIN_MARKET_BREADTH=0.55
MAX_DAY_CHANGE=4.0
MIN_SCORE=0.72
MIN_SCORE_MARGIN=0.05

@dataclass(frozen=True)
class IntradaySignal:
    symbol:str
    session_day:str
    entry_price:float
    target_price:float
    score:float
    market_breadth:float
    day_change_pct:float
    relative_strength_pct:float
    swept_low:bool
    displacement:bool
    fvg_retrace:bool
    bar_time:str

    def line(self)->str:
        return (f"BUY {self.symbol} @ {self.entry_price:.4f} | "
                f"TP {self.target_price:.4f} (+2.0%) | score {self.score:.2f} | "
                f"breadth {self.market_breadth:.0%} | day {self.day_change_pct:+.2f}% | "
                f"RS {self.relative_strength_pct:+.2f}% | "
                f"sweep {'yes' if self.swept_low else 'no'} | "
                f"displacement {'yes' if self.displacement else 'no'} | "
                f"FVG {'yes' if self.fvg_retrace else 'no'} | {self.bar_time} PKT")

def _five_minute(df:pd.DataFrame)->pd.DataFrame:
    x=df.copy()
    x["bar_time"]=pd.to_datetime(x["bar_time"],errors="coerce")
    x=x.dropna(subset=["bar_time"]).sort_values(["symbol","bar_time"])
    out=[]
    for symbol,g in x.groupby("symbol",sort=False):
        z=g.set_index("bar_time").resample("5min",label="right",closed="right").agg(
            open=("open","first"),high=("high","max"),low=("low","min"),close=("close","last")
        ).dropna()
        z["symbol"]=symbol
        out.append(z.reset_index())
    return pd.concat(out,ignore_index=True) if out else pd.DataFrame()

def _features(g:pd.DataFrame):
    if len(g)<MIN_BARS:return None
    g=g.sort_values("bar_time").reset_index(drop=True)
    last=g.iloc[-1]; prior=g.iloc[:-1]
    prior_low=float(prior["low"].tail(12).min())
    prior_high=float(prior["high"].tail(12).max())
    rng=float(last["high"]-last["low"])
    med=float((g["high"]-g["low"]).tail(12).median())
    if not math.isfinite(rng) or rng<=0 or not math.isfinite(med):return None
    swept=float(last["low"])<prior_low and float(last["close"])>prior_low
    displacement=(float(last["close"])>prior_high and rng>=med*1.30
                  and float(last["close"])>float(last["open"]))
    fvg=False
    if len(g)>=4:
        a,b,c=g.iloc[-3],g.iloc[-2],g.iloc[-1]
        gap=float(b["low"])>float(a["high"])
        mid=(float(b["low"])+float(a["high"]))/2
        fvg=gap and float(c["low"])<=mid<=float(c["close"])
    return {"last":float(last["close"]),"swept":swept,"displacement":displacement,
            "fvg":fvg,"bar_time":last["bar_time"],"session_high":float(g["high"].max())}

def choose(partial:pd.DataFrame,history:pd.DataFrame,universe_size:int,session_day:str):
    if partial.empty:return None,"no fresh intraday bars"
    coverage=partial["symbol"].nunique()/max(universe_size,1)
    if coverage<MIN_COVERAGE:return None,f"coverage {coverage:.1%} below {MIN_COVERAGE:.0%}"
    h=history.copy();h["date"]=pd.to_datetime(h["date"])
    prior=h[h["date"].dt.date.astype(str)<session_day]
    if prior["date"].dt.date.nunique()<MIN_HISTORY_SESSIONS:return None,"insufficient prior daily history"
    prev=(prior.sort_values("date").groupby("symbol",sort=False).tail(1)[["symbol","close"]]
          .rename(columns={"close":"prev_close"}))
    px=partial.groupby("symbol",sort=False).tail(1).merge(prev,on="symbol",how="inner")
    if px.empty:return None,"no symbols with prior close"
    px["day_change_pct"]=(px["close"]/px["prev_close"]-1)*100
    breadth=float((px["day_change_pct"]>0).mean())
    if breadth<MIN_MARKET_BREADTH:return None,f"KMIALL breadth {breadth:.1%} below {MIN_MARKET_BREADTH:.0%}"
    market_return=float(px["day_change_pct"].median())
    candidates=[]
    for symbol,g in _five_minute(partial).groupby("symbol",sort=False):
        row=px[px["symbol"]==symbol]
        if row.empty:continue
        f=_features(g)
        if f is None:continue
        change=float(row["day_change_pct"].iloc[0]);price=f["last"]
        if change<=0 or change>MAX_DAY_CHANGE or price<=0:continue
        off_high=(f["session_high"]-price)/price*100 if f["session_high"] else 99
        if off_high>3:continue
        rs=change-market_return
        structural=int(f["swept"])+int(f["displacement"])+int(f["fvg"])
        score=(.30*int(f["swept"])+.25*int(f["displacement"])+.20*int(f["fvg"])+
               .15*min(max(rs,0)/3,1)+.10*min(max(breadth-.55,0)/.30,1))
        if structural<2 or rs<.25 or score<MIN_SCORE:continue
        candidates.append(IntradaySignal(symbol,session_day,price,price*1.02,score,breadth,
                                         change,rs,bool(f["swept"]),bool(f["displacement"]),
                                         bool(f["fvg"]),f["bar_time"].strftime("%H:%M")))
    if not candidates:return None,"no KMIALL candidate cleared all hard gates"
    candidates.sort(key=lambda s:(-s.score,-s.relative_strength_pct,s.symbol))
    if len(candidates)>1 and candidates[0].score-candidates[1].score<MIN_SCORE_MARGIN:
        return None,"top candidates too close to justify one winner"
    return candidates[0],f"one winner from {len(candidates)} qualified candidates"

def validate_signal(signal:IntradaySignal):
    if not signal.symbol or signal.entry_price<=0:raise ValueError("invalid signal")
    if not math.isclose(signal.target_price,signal.entry_price*1.02,rel_tol=1e-12):
        raise ValueError("target must be exactly +2% from entry")
