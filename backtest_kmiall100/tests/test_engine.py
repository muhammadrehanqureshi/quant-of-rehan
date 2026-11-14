"""The trade simulator, one rule at a time."""

import numpy as np

from kmiall100 import engine as E


def bars(rows):
    a = np.array(rows, dtype=float)
    o, h, l, c, v = a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4]
    return o, h, l, c, v


def run(rows, sig, tp=0.02, sl=0.01, trail=0.0, hold=10, flat_eod=False, eod=None, slip=0.0):
    o, h, l, c, v = bars(rows)
    n = len(c)
    eod = np.zeros(n, dtype=bool) if eod is None else np.array(eod, dtype=bool)
    si = np.array(sig, dtype=np.int64)
    m = len(si)
    return E.simulate(o, h, l, c, v, eod, si, np.full(m, tp), np.full(m, sl), np.full(m, trail), hold, flat_eod,
                      np.zeros(n, dtype=bool), False, slip)


def test_tp_fills_exactly_at_the_target_even_on_a_gap_up():
    rows = [(100, 100, 100, 100, 9), (100, 100.5, 99.8, 100.2, 9), (105, 106, 104, 105, 9)]
    _, en, ex, epx, xpx, out, _, _ = run(rows, [0])
    assert out[0] == E.OUT_TP and abs(xpx[0] - 102.0) < 1e-9 and ex[0] == 2


def test_stop_wins_when_one_bar_touches_both():
    rows = [(100, 100, 100, 100, 9), (100, 100.5, 99.9, 100, 9), (100, 103, 98, 100, 9)]
    _, _, _, _, xpx, out, _, _ = run(rows, [0])
    assert out[0] == E.OUT_SL and abs(xpx[0] - 99.0) < 1e-9


def test_gap_through_the_stop_fills_at_the_open():
    rows = [(100, 100, 100, 100, 9), (100, 100.4, 99.9, 100, 9), (97, 98, 96, 97, 9)]
    _, _, _, _, xpx, out, _, _ = run(rows, [0])
    assert out[0] == E.OUT_GAP and abs(xpx[0] - 97.0) < 1e-9


def test_entry_is_next_open_and_slippage_hurts_both_sides():
    rows = [(100, 100, 100, 100, 9), (101, 101.2, 100.9, 101, 9), (101, 101.2, 100.5, 101, 9)]
    _, _, _, epx, xpx, out, _, _ = run(rows, [0], tp=0.5, sl=0.5, hold=2, slip=0.001)
    assert abs(epx[0] - 101 * 1.001) < 1e-9            # bought above the open
    assert out[0] == E.OUT_TIME and abs(xpx[0] - 101 * 0.999) < 1e-9


def test_take_profit_pays_no_slippage():
    rows = [(100, 100, 100, 100, 9), (100, 100.2, 99.9, 100, 9), (100, 103, 100, 102, 9)]
    _, _, _, epx, xpx, out, _, _ = run(rows, [0], slip=0.001)
    assert out[0] == E.OUT_TP and abs(xpx[0] - epx[0] * 1.02) < 1e-9


def test_time_stop_exits_at_the_close_of_the_last_allowed_bar():
    rows = [(100, 100, 100, 100, 9)] + [(100, 100.3, 99.8, 100.1, 9)] * 6
    _, en, ex, _, xpx, out, _, _ = run(rows, [0], hold=3)
    assert out[0] == E.OUT_TIME and ex[0] - en[0] == 2 and abs(xpx[0] - 100.1) < 1e-9


def test_flat_at_end_of_day():
    rows = [(100, 100, 100, 100, 9), (100, 100.3, 99.8, 100.1, 9), (100, 100.3, 99.8, 100.2, 9), (100, 100.3, 99.8, 100.3, 9)]
    _, _, ex, _, xpx, out, _, _ = run(rows, [0], hold=10, flat_eod=True, eod=[0, 0, 1, 0])
    assert out[0] == E.OUT_EOD and ex[0] == 2 and abs(xpx[0] - 100.2) < 1e-9


def test_signal_on_the_last_bar_is_dropped_and_zero_volume_next_bar_is_not_tradable():
    rows = [(100, 100, 100, 100, 9), (100, 100.3, 99.8, 100.1, 0), (100, 100.3, 99.8, 100.2, 9)]
    r = run(rows, [2])
    assert len(r[0]) == 0
    r = run(rows, [0])
    assert len(r[0]) == 0


def test_one_position_at_a_time():
    rows = [(100, 100, 100, 100, 9)] + [(100, 100.3, 99.8, 100.0, 9)] * 8
    r = run(rows, [0, 1, 2, 5], hold=4)
    assert len(r[0]) == 2 and r[0][0] == 0 and r[0][1] >= r[2][0]


def test_trailing_stop_uses_completed_bars_only():
    # bar 2 spikes to 104 and falls back inside the same candle. The stop must not be raised by that candle
    # (so no exit on bar 2), and from bar 3 it trails 3 percent under 104.
    rows = [(100, 100, 100, 100, 9), (100, 100.2, 99.9, 100, 9), (100, 104, 99.6, 100, 9), (101.5, 101.8, 99.8, 100, 9)]
    _, _, ex, _, xpx, out, _, _ = run(rows, [0], tp=0.5, sl=0.05, trail=0.03, hold=4)
    assert out[0] == E.OUT_SL and ex[0] == 3 and abs(xpx[0] - 104 * 0.97) < 1e-9


def test_costs_and_tax():
    gross, net = E.net_returns(np.array([100.0, 100.0]), np.array([102.0, 99.0]))
    assert abs(net[0] - (0.02 - 2 * 0.00224) * 0.85) < 1e-12      # winners pay 15 percent tax
    assert abs(net[1] - (-0.01 - 2 * 0.00224)) < 1e-12            # losers do not get a refund


def test_jump_mask_flags_the_neighbourhood_of_a_bad_print():
    c = np.full(300, 100.0)
    c[150:] = 40.0
    m = E.jump_mask(c)
    assert m[150] and m[100] and not m[10] and not m[290]
