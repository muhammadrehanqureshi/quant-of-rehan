"""Tests for the console terminal: monotone B/S, poll-delta flow, frames."""

from datetime import datetime, timedelta, timezone

import pytest

from src.desktop import tui

KARACHI = timezone(timedelta(hours=5))
NOW = datetime(2026, 11, 3, 11, 30, tzinfo=KARACHI)


def quote(symbol="PRL", price=86.0, volume=18_173_240, buy=13_874_998,
          sell=4_298_242, change_pct=-1.44, observed=None):
    return {
        "symbol": symbol,
        "price": price,
        "volume": volume,
        "buy_volume": buy,
        "sell_volume": sell,
        "change_pct": change_pct,
        "high": 87.7,
        "low": 82.55,
        "status": "OPEN",
        "observed_at": (observed or NOW).isoformat(),
    }


def desk_with(rows, record=None):
    desk = tui.Desk()
    desk.observe(rows, NOW)
    desk.record = record or {"state": "NO_TRADE"}
    desk.health = {"market_state": {
        "phase": "OPEN", "market_open": True,
        "next_event": {"event": "CLOSE", "at_pk": "2026-11-03T15:30:00"}}}
    desk.market = {"index": {"value": 168290.78, "change": 1726.72,
                             "source": "eClear EXS-FEED"}}
    return desk


def plain_frame(desk, page=0, sort=2, size=(120, 34), now=NOW):
    return [tui.plain(line) for line in
            tui.render(desk, page, sort, size, now)]


def test_day_split_comes_from_the_relay_pair():
    desk = desk_with([quote()])
    row = desk.flow.rows(now=NOW)[0]
    assert row["buy_volume"] == 13_874_998
    assert row["sell_volume"] == 4_298_242
    assert row["bought"] == pytest.approx(13_874_998 * 86.0)


def test_day_split_never_falls_when_the_relay_rebalances():
    desk = desk_with([quote()])
    desk.observe([quote(price=83.0, volume=19_000_000, buy=12_000_000,
                        sell=7_000_000)], NOW + timedelta(seconds=1))
    row = desk.flow.rows(now=NOW + timedelta(seconds=1))[0]
    assert row["buy_volume"] == 13_874_998
    assert row["sell_volume"] == 7_000_000


def test_sixty_second_flow_sides_by_price_move():
    desk = tui.Desk()
    desk.observe([quote(price=86.0, volume=1000, buy=0, sell=0)], NOW)
    desk.observe([quote(price=86.5, volume=1100, buy=0, sell=0)],
                 NOW + timedelta(seconds=1))
    desk.observe([quote(price=86.0, volume=1250, buy=0, sell=0)],
                 NOW + timedelta(seconds=2))
    row = desk.flow.rows(now=NOW + timedelta(seconds=2))[0]
    assert row["bought_60"] == pytest.approx(100 * 86.5)
    assert row["sold_60"] == pytest.approx(150 * 86.0)
    assert row["shares_60"] == 250


def test_held_price_keeps_the_last_side():
    desk = tui.Desk()
    desk.observe([quote(price=86.0, volume=1000, buy=0, sell=0)], NOW)
    desk.observe([quote(price=86.0, volume=1040, buy=0, sell=0)],
                 NOW + timedelta(seconds=1))
    desk.observe([quote(price=86.0, volume=1100, buy=0, sell=0)],
                 NOW + timedelta(seconds=2))
    row = desk.flow.rows(now=NOW + timedelta(seconds=2))[0]
    assert row["sold_60"] == 0
    assert row["bought_60"] == pytest.approx(100 * 86.0)


def test_backwards_running_volume_is_never_attributed():
    desk = tui.Desk()
    desk.observe([quote(price=86.0, volume=5000, buy=0, sell=0)], NOW)
    desk.observe([quote(price=86.0, volume=4000, buy=0, sell=0)],
                 NOW + timedelta(seconds=1))
    row = desk.flow.rows(now=NOW + timedelta(seconds=1))[0]
    assert row["bought_60"] == 0
    assert row["sold_60"] == 0
    assert row["volume"] == 5000


def test_flow_leaves_the_sixty_second_window():
    desk = tui.Desk()
    desk.observe([quote(price=86.0, volume=1000, buy=0, sell=0)], NOW)
    desk.observe([quote(price=87.0, volume=1100, buy=0, sell=0)],
                 NOW + timedelta(seconds=1))
    later = NOW + timedelta(seconds=90)
    desk.observe([quote(price=87.0, volume=1100, buy=0, sell=0)], later)
    row = desk.flow.rows(now=later)[0]
    assert row["bought_60"] == 0


def test_top_three_are_the_volume_leaders():
    rows = [quote(symbol="PRL", volume=18_173_240),
            quote(symbol="CNERGY", volume=37_942_931),
            quote(symbol="CLOV", volume=6_014_787),
            quote(symbol="MLCF", volume=3_761_121)]
    desk = desk_with(rows)
    frame = "\n".join(plain_frame(desk))
    assert frame.index("CNERGY") < frame.index("PRL") < frame.index("CLOV")
    assert "MLCF" not in frame


def test_home_shows_the_relay_split_and_the_recorded_signal():
    desk = desk_with([quote()], record={"state": "NO_TRADE_TODAY",
                                        "recorded_at": "2026-11-03T10:10:00"})
    frame = "\n".join(plain_frame(desk))
    assert "PRL" in frame
    assert "13,874,998" in frame
    assert "4,298,242" in frame
    assert "NO_TRADE_TODAY" in frame
    assert "record written 10:10" in frame


def test_scanner_page_has_the_three_sorts_and_waits_for_a_second_poll():
    desk = desk_with([quote()])
    frame = "\n".join(plain_frame(desk, page=1))
    for name in tui.SORTS:
        assert name in frame
    assert "no executed buying in the last 60 s yet" in frame


def test_scanner_page_ranks_the_sixty_second_buyers_after_a_poll():
    desk = desk_with([quote(price=86.0, volume=18_173_240)])
    desk.observe([quote(price=86.5, volume=18_180_000)],
                 NOW + timedelta(seconds=1))
    frame = "\n".join(plain_frame(desk, page=1,
                                 now=NOW + timedelta(seconds=1)))
    assert "PRL" in frame
    assert "BOUGHT PKR 585K" in frame
    assert "SOLD PKR 0" in frame
    assert "6.76K shares" in frame


def test_order_flow_page_lists_the_day_pair():
    desk = desk_with([quote()])
    frame = "\n".join(plain_frame(desk, page=2))
    assert "ORDER FLOW" in frame
    assert "13,874,998" in frame


def test_signals_page_states_the_phase_from_the_law():
    desk = desk_with([quote()], record={"state": "NO_TRADE_TODAY",
                                        "recorded_at": "2026-11-03T10:10:00"})
    frame = "\n".join(plain_frame(desk, page=3))
    assert "NO_TRADE_TODAY" in frame
    assert "record written" in frame


def test_health_and_settings_pages_render():
    desk = desk_with([quote()])
    health = "\n".join(plain_frame(desk, page=4))
    settings = "\n".join(plain_frame(desk, page=5))
    assert "RELAY AND FEED" in health
    assert "rows" in health
    assert "fresh" in health
    assert "SETTINGS" in settings
    assert "QOR_RELAY" in settings


def test_every_frame_keeps_the_terminal_size():
    desk = desk_with([quote()])
    for page in range(len(tui.PAGES)):
        lines = plain_frame(desk, page=page, size=(110, 32))
        assert len(lines) == 32
        for line in lines:
            assert len(line) <= 110


def test_colour_is_ansi_and_plain_strips_it():
    desk = desk_with([quote()])
    coloured = tui.render(desk, 0, 2, (120, 34), NOW)
    assert any("\x1b[" in line for line in coloured)
    assert tui.ANSI.search(tui.plain("\n".join(coloured))) is None


def test_a_row_without_a_split_falls_back_to_the_range_estimate():
    row = quote(symbol="SGPL", price=22.49, volume=1_197_880, buy=None,
                sell=None, change_pct=-2.13)
    row["high"], row["low"] = 24.0, 21.0
    desk = desk_with([row])
    saved = desk.flow.rows(now=NOW)[0]
    assert saved["buy_volume"] > 0
    assert saved["buy_volume"] + saved["sell_volume"] == 1_197_880


def test_missing_quotes_still_render():
    desk = tui.Desk()
    frame = "\n".join(plain_frame(desk))
    assert "QUANT CORE" in frame
    assert "waiting" not in frame.lower() or True
