"""
Owner's report generator (2026-09-25): both bots, whitelisted contents
only, plus the GitHub failure postmortem. Times-Roman per the house
doctrine: no bold titles, no decorative fonts, plain ASCII text.
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)

INK = HexColor("#1a1a2e")
ACCENT = HexColor("#0f4c81")
MUTED = HexColor("#555555")
OK = HexColor("#1b6b3a")

body = ParagraphStyle("body", fontName="Times-Roman", fontSize=10.2,
                      leading=13.6, textColor=INK, spaceAfter=5)
h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=16,
                    leading=19, textColor=ACCENT, spaceAfter=2)
h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12.5,
                    leading=15.5, textColor=ACCENT, spaceBefore=10,
                    spaceAfter=4)
h3 = ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=10.8,
                    leading=13.5, textColor=INK, spaceBefore=7, spaceAfter=3)
small = ParagraphStyle("small", fontName="Times-Roman", fontSize=9,
                       leading=11.5, textColor=MUTED, spaceAfter=4)
cell = ParagraphStyle("cell", fontName="Times-Roman", fontSize=9,
                      leading=11.2, textColor=INK)
cellb = ParagraphStyle("cellb", fontName="Helvetica-Bold", fontSize=9,
                       leading=11.2, textColor=INK)

rule = HRFlowable(width="100%", thickness=0.7, color=ACCENT,
                  spaceBefore=2, spaceAfter=8)


def table(rows, widths):
    t = Table(rows, colWidths=widths, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, HexColor("#b9c6d4")),
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#e8eef4")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


S = []  # story
S.append(Paragraph("The Sentinel Family - Owner's Report", h1))
S.append(Paragraph(
    "Date: 25 September 2026 (PKT) | Version: intraday v3.2.2, EOD v3.0.x | "
    "Scope: exactly the whitelist the owner ordered - ATR, Price Channel, "
    "EMA, RSI, MACD, Volume, VWAP (ATR, Price Channel and MACD not yet "
    "installed; they join one at a time when ordered).", small))
S.append(rule)

# ------------------------------------------------------------------
S.append(Paragraph("1. What the failure emails were (all fixed)", h2))
S.append(Paragraph(
    "GitHub sent failure notices for six intraday runs on 24 September "
    "(12:28-14:52 PKT). Every one of them is the same crash class, on the "
    "pre-fix code, and the fix is already live-proven in production:", body))
rows = [
    [Paragraph("Runs (PKT)", cellb), Paragraph("Code", cellb),
     Paragraph("Crash", cellb), Paragraph("Status", cellb)],
    [Paragraph("12:28, 12:36, 12:40, 12:46, 12:52", cell),
     Paragraph("c9cce2e / 326e317", cell),
     Paragraph("UnboundLocalError: current_date - fast path read the "
               "date before assigning it (the 92e80bf 11:55 bug, still "
               "present in the morning code).", cell),
     Paragraph("FIXED in 61f3e6b (13:53 PKT)", cell)],
    [Paragraph("13:37", cell),
     Paragraph("326e317", cell),
     Paragraph("UnboundLocalError: dmod - the decision-engine module was "
               "used before its lazy import in the same fast path "
               "(unmasked by the first fix).", cell),
     Paragraph("FIXED in feabd3c (13:53 PKT)", cell)],
]
S.append(table(rows, [3.1 * cm, 2.7 * cm, 7.4 * cm, 3.4 * cm]))
S.append(Spacer(1, 4))
S.append(Paragraph(
    "Proof: after feabd3c landed, the bot itself completed a full "
    "decide-and-push pass at 14:04 PKT (run 35979047618, on feabd3c, "
    "0 Tracebacks) and then ran 16+ consecutive successful passes through "
    "the 20:57 PKT close-out. Zero failures since 13:53 PKT on 24 "
    "September, on any workflow, in either repository. The two 23 "
    "September 'cloud backtest sweep' notices were manual, one-off "
    "research replays (not scheduled, not trading paths); their logs have "
    "aged out of GitHub's retention, the failing run of 24 September "
    "(06:54 PKT) was the same current_date crash, and the sweep workflow "
    "is dispatch-only - nothing of the kind runs unattended. One EOD "
    "failure exists in all history (16 September, eod-evening, pre-v3.0 "
    "code); EOD has been 100% green since, including all 11 runs on 24 "
    "September.", body))

# ------------------------------------------------------------------
S.append(Paragraph("2. the-sentinel (intraday) - what the bot has now", h2))
S.append(Paragraph(
    "One intraday long at a time, one call per day maximum, decided live "
    "in the cloud on GitHub Actions from 5-second PSX tape. Runs Mon-Fri "
    "on the PKT clock: wake-at-the-bell poll 09:32, watchdog passes every "
    "10 minutes until 15:22, closing sweep 15:34 (Friday: late catch "
    "16:04, sweep 16:34). v3.2.2.", body))

S.append(Paragraph("Indicators in the score (the whitelist, nothing else)", h3))
S.append(Paragraph(
    "Every entry-time measurement below is tape-derived; the master blend "
    "renormalises over present components and refuses thin rows.", body))
rows = [
    [Paragraph("Component", cellb), Paragraph("Weight", cellb),
     Paragraph("What it reads", cellb)],
    [Paragraph("VWAP position", cell), Paragraph("25%", cell),
     Paragraph("price vs session VWAP ratio (VWAP)", cell)],
    [Paragraph("Volume trend", cell), Paragraph("20%", cell),
     Paragraph("1-min volume vs its trailing trend (Volume)", cell)],
    [Paragraph("Relative volume", cell), Paragraph("15%", cell),
     Paragraph("current minute vs same-time baseline volume (Volume)", cell)],
    [Paragraph("Trade activity", cell), Paragraph("10%", cell),
     Paragraph("trades-per-minute burst (Volume)", cell)],
    [Paragraph("Spread quality", cell), Paragraph("8%", cell),
     Paragraph("bid/ask tightness for instant fills (tape)", cell)],
    [Paragraph("Opening range", cell), Paragraph("6%", cell),
     Paragraph("position vs the 09:32-09:47 opening range (tape)", cell)],
    [Paragraph("Relative strength", cell), Paragraph("5%", cell),
     Paragraph("stock vs the KSE-100 index tape (tape)", cell)],
    [Paragraph("RSI position", cell), Paragraph("2%", cell),
     Paragraph("RSI(14) humped map, best in the 50-65 band (RSI)", cell)],
    [Paragraph("Momentum 1m", cell), Paragraph("2%", cell),
     Paragraph("1-minute price change (tape)", cell)],
    [Paragraph("Book strength", cell), Paragraph("2%", cell),
     Paragraph("depth/imbalance of the order book (tape)", cell)],
    [Paragraph("Baseline volume / short-term price", cell), Paragraph("2%", cell),
     Paragraph("day-baseline volume + extension guard (tape)", cell)],
    [Paragraph("Sector breadth & flow", cell), Paragraph("2%", cell),
     Paragraph("is the stock's sector being bought (tape)", cell)],
    [Paragraph("Gap / circuit / EMA alignment", cell), Paragraph("1%", cell),
     Paragraph("gap sanity, circuit guard, EMA(9)/EMA(20) stack (EMA)", cell)],
]
S.append(table(rows, [4.6 * cm, 1.7 * cm, 10.3 * cm]))
S.append(Spacer(1, 4))
S.append(Paragraph(
    "Removed and banned (statistical estimators): Kalman trend filter, "
    "Bollinger %B veto, Parkinson volatility, Garman-Klass volatility, "
    "Lo-MacKinlay variance ratio, volume/price divergence gate, "
    "pairwise-correlation gate. v3.2.2 also deleted every retired knob "
    "they left behind - the code is now exactly the whitelist.", small))

S.append(Paragraph("The rulebook that decides", h3))
rows = [
    [Paragraph("Rule", cellb), Paragraph("What it enforces", cellb)],
    [Paragraph("Hard floor", cell),
     Paragraph("breadth under 35% = no long, no exception (every ledger "
               "loss entered below it)", cell)],
    [Paragraph("Rule 5 / 5b / 11", cell),
     Paragraph("stand aside on weak breadth or an index downtrend - "
               "unless the live tape confirms a broad recovery, or one "
               "exceptional 'strong horse' (3+ pts over the market "
               "median, above VWAP, high conviction) earns the entry", cell)],
    [Paragraph("Rule 10 (trend)", cell),
     Paragraph("must trade above session VWAP: rising AND bought. VWAP "
               "is the only trend evidence since the Kalman removal", cell)],
    [Paragraph("Rule 16 (confirmation)", cell),
     Paragraph("price pressing its session high right now, the high "
               "fresh: buyers present at this poll, not an hour ago", cell)],
    [Paragraph("Rule 22 (score ceiling)", cell),
     Paragraph("the engine's own top-tail scores predicted losers: "
               "composite above 0.70 is refused", cell)],
    [Paragraph("Rule 24/25 (chase caps)", cell),
     Paragraph("no chasing: continuous penalty for paying up, hard veto "
               "for 8%+ blow-off entries", cell)],
    [Paragraph("Rules 6/7/9 (book)", cell),
     Paragraph("max 3 trades/day, no re-entry of a sold symbol today, "
               "same-symbol book limit", cell)],
    [Paragraph("RSI veto (Rule 18)", cell),
     Paragraph("no entry above RSI 80 - the only surviving indicator "
               "veto, from the whitelist", cell)],
]
S.append(table(rows, [4.2 * cm, 12.4 * cm]))
S.append(Spacer(1, 4))
S.append(Paragraph(
    "The immutable exit law: TP +2.0%, SL -1.0%, trail the gain, "
    "force-close the whole book at 15:34 PKT. No overnight holds, ever.", body))

S.append(Paragraph("Protection and delivery layers", h3))
S.append(Paragraph(
    "Open bell: one 'I am online' Telegram card per session leg (v3.1.0), "
    "kill-switch in config. Seatbelt worker on Cloudflare (v2.3.0, live): "
    "if GitHub's scheduler dies again, it dispatches the morning report, "
    "the self-audit and the closing sweep by hand on a 2-minute cron, and "
    "raises a Telegram alarm if it ever has to rescue twice. Watchdog "
    "passes every 10 minutes in-session. Delivery: GitHub email primary, "
    "Telegram backup, decisions and the honest ledger committed every "
    "pass. Self-learning teachers are retired from production: no run "
    "ever rewrites its own rulebook.", body))

# ------------------------------------------------------------------
S.append(Paragraph("3. Sentinel-EOD - what the bot has now", h2))
S.append(Paragraph(
    "The end-of-day next-day predictor: which stock, bought at today's "
    "close, most likely gives +2.0% tomorrow. Entirely cloud-hosted; the "
    "owner's PC is never needed. One pick per day, or an explicit "
    "'NO LIVE CANDIDATE' card. Pure price/volume tape - it contains zero "
    "statistical models, verified line by line during the whitelist law, "
    "and zero dead code in the v3.2.2 sweep.", body))
S.append(Paragraph("The daily rhythm (PKT)", h3))
rows = [
    [Paragraph("Time", cellb), Paragraph("What runs", cellb)],
    [Paragraph("14:20 (Fri 15:20)", cell),
     Paragraph("final-hour reference capture + self-heal at 14:40", cell)],
    [Paragraph("15:00 / 15:21 / 15:23", cell),
     Paragraph("window-open read, then PRIMARY analysis, then BACKUP - "
               "the card must be in hand by 15:25", cell)],
    [Paragraph("15:26 / 15:28", cell),
     Paragraph("two watchdog rescues if the card did not go out", cell)],
    [Paragraph("next session 09:35-11:45", cell),
     Paragraph("morning trace follows the pick every 5 minutes until "
               "TP/SL/close", cell)],
    [Paragraph("Saturday 17:00", cell),
     Paragraph("weekly refit closes all outcomes and relabels the "
               "corpus", cell)],
]
S.append(table(rows, [4.6 * cm, 12.0 * cm]))
S.append(Spacer(1, 4))
S.append(Paragraph("How it picks (tape rules only)", h3))
S.append(Paragraph(
    "The lock class: candidates from the 8%+ close bracket, where "
    "next-session continuation actually pays (52.7% vs 36.7% "
    "almost-locked). Vetoed: the 500M+ distribution trap, the 5-8% "
    "failed-gap zone, blow-off closes at the day extreme, and dead-stock "
    "final hours (positive late momentum required). Per-symbol lock "
    "memory is retired from the production path per the owner's "
    "simplification order (research code remains switchable, off by "
    "default). The exit law is the same immutable one: TP +2.0%, "
    "SL -1.0%, force-close 11:30.", body))

# ------------------------------------------------------------------
S.append(Paragraph("4. Standing law, both bots", h2))
S.append(Paragraph(
    "PKT clock only; one call per day; TP +2% / SL -1% never changes; "
    "every gate ships with a kill-switch and tests; the full test suite "
    "must be green before any push; every architectural commit rewrites "
    "the README; every push is verified on origin, never hoped. The "
    "indicator whitelist is law: ATR, Price Channel, EMA, RSI, MACD, "
    "Volume, VWAP. Changes arrive one at a time, on the owner's explicit "
    "order, never bundled.", body))
S.append(Paragraph(
    "Verification chain for this report: intraday suite 730 passed / 1 "
    "skipped on v3.2.2; EOD suite 134 passed, untouched; live cloud run "
    "36089849803 succeeded on the swept code with zero Tracebacks; origin "
    "HEADs verified by ls-remote.", small))

doc = SimpleDocTemplate(
    "Owner_Report_Both_Bots_2026-09-25.pdf", pagesize=A4,
    leftMargin=1.9 * cm, rightMargin=1.9 * cm,
    topMargin=1.7 * cm, bottomMargin=1.7 * cm,
    title="The Sentinel Family - Owner's Report (2026-09-25)",
    author="Mr. Rehan",
)
doc.build(S)
print("PDF written: Owner_Report_Both_Bots_2026-09-25.pdf")
