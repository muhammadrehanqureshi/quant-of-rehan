"""
Trading-session arithmetic.

Every boundary here is one the pipeline gets wrong if the schedule is wrong:
the Friday split decides where tick-to-tick features may be computed, and the
trading date decides where cumulative counters reset.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

from psx_core import sessions

# 2026-09-02 is a Wednesday, 2026-09-04 a Friday, 2026-09-05 a Saturday.
WEDNESDAY = date(2026, 9, 2)
FRIDAY = date(2026, 9, 4)
SATURDAY = date(2026, 9, 5)
SUNDAY = date(2026, 9, 6)


def pkt(day: date, hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(
        day.year, day.month, day.day, hour, minute, second, tzinfo=sessions.PKT
    )


def test_weekday_calendar_matches_the_published_schedule():
    assert WEDNESDAY.weekday() == 2
    assert FRIDAY.weekday() == 4
    assert SATURDAY.weekday() == 5


class TestLegs:
    def test_monday_to_thursday_is_one_leg(self):
        legs = sessions.legs_for(WEDNESDAY)
        assert len(legs) == 1
        assert legs[0].index == 1
        assert legs[0].start == time(9, 32)
        assert legs[0].end == time(15, 30)

    def test_friday_is_split_in_two(self):
        legs = sessions.legs_for(FRIDAY)
        assert len(legs) == 2
        assert (legs[0].start, legs[0].end) == (time(9, 17), time(12, 0))
        assert (legs[1].start, legs[1].end) == (time(14, 32), time(16, 30))

    def test_weekend_has_no_legs(self):
        assert sessions.legs_for(SATURDAY) == ()
        assert sessions.legs_for(SUNDAY) == ()

    def test_is_trading_day(self):
        assert sessions.is_trading_day(WEDNESDAY)
        assert sessions.is_trading_day(FRIDAY)
        assert not sessions.is_trading_day(SATURDAY)
        assert not sessions.is_trading_day(SUNDAY)


class TestIsOpen:
    @pytest.mark.parametrize(
        "hour,minute,expected",
        [
            (9, 31, False),   # one minute before the bell
            (9, 32, True),    # the bell
            (12, 0, True),    # Mon-Thu has no lunch break
            (15, 29, True),
            (15, 30, False),  # close is exclusive
            (16, 0, False),
        ],
    )
    def test_midweek_boundaries(self, hour, minute, expected):
        assert sessions.is_open(pkt(WEDNESDAY, hour, minute)) is expected

    @pytest.mark.parametrize(
        "hour,minute,expected",
        [
            (9, 16, False),
            (9, 17, True),    # Friday opens 15 minutes earlier
            (11, 59, True),
            (12, 0, False),   # lunch break starts
            (13, 0, False),   # the gap the collector must not poll through
            (14, 31, False),
            (14, 32, True),   # afternoon leg
            (16, 29, True),
            (16, 30, False),
        ],
    )
    def test_friday_boundaries(self, hour, minute, expected):
        assert sessions.is_open(pkt(FRIDAY, hour, minute)) is expected

    def test_weekend_is_never_open(self):
        for hour in range(0, 24):
            assert not sessions.is_open(pkt(SATURDAY, hour, 30))


class TestCurrentLeg:
    def test_friday_morning_is_leg_one(self):
        leg = sessions.current_leg(pkt(FRIDAY, 10, 0))
        assert leg is not None and leg.index == 1

    def test_friday_afternoon_is_leg_two(self):
        leg = sessions.current_leg(pkt(FRIDAY, 15, 0))
        assert leg is not None and leg.index == 2

    def test_friday_lunch_has_no_leg(self):
        assert sessions.current_leg(pkt(FRIDAY, 13, 0)) is None


class TestTradingDate:
    def test_friday_afternoon_shares_the_morning_trading_date(self):
        """
        The lunch break splits the session but not the day. Cumulative volume
        and trade counters run continuously across it, so both legs must map to
        the same trading date or the afternoon's first volume_delta is a
        fabricated jump from zero.
        """
        morning = sessions.trading_date(pkt(FRIDAY, 10, 0))
        afternoon = sessions.trading_date(pkt(FRIDAY, 15, 0))
        assert morning == afternoon == FRIDAY

    def test_derived_from_pakistan_time_not_utc(self):
        """
        09:35 PKT is 04:35 UTC the same day, but 23:00 PKT would be 18:00 UTC
        -- using UTC dates would put an early-morning PKT session on the
        previous calendar day for any schedule that opened before 05:00 PKT.
        """
        moment = pkt(WEDNESDAY, 9, 35).astimezone(timezone.utc)
        assert sessions.trading_date(moment) == WEDNESDAY

    def test_naive_input_is_treated_as_utc(self):
        naive = datetime(2026, 9, 2, 5, 30)
        assert sessions.trading_date(naive) == WEDNESDAY


class TestSessionId:
    def test_friday_legs_get_distinct_ids(self):
        morning = sessions.session_id(pkt(FRIDAY, 10, 0))
        afternoon = sessions.session_id(pkt(FRIDAY, 15, 0))
        assert morning != afternoon
        assert morning.endswith("#1")
        assert afternoon.endswith("#2")
        assert morning.startswith(FRIDAY.isoformat())


class TestNextOpen:
    def test_before_the_bell_returns_todays_open(self):
        moment = pkt(WEDNESDAY, 8, 0)
        assert sessions.next_open(moment) == pkt(WEDNESDAY, 9, 32)

    def test_friday_lunch_returns_the_afternoon_leg(self):
        moment = pkt(FRIDAY, 13, 0)
        assert sessions.next_open(moment) == pkt(FRIDAY, 14, 32)

    def test_saturday_skips_the_weekend_to_monday(self):
        opens = sessions.next_open(pkt(SATURDAY, 12, 0))
        assert opens.date().weekday() == 0
        assert opens.time() == time(9, 32)

    def test_after_the_close_returns_the_next_day(self):
        opens = sessions.next_open(pkt(WEDNESDAY, 16, 0))
        assert opens.date() == WEDNESDAY + timedelta(days=1)

    def test_always_returns_a_moment_in_the_future(self):
        for day in (WEDNESDAY, FRIDAY, SATURDAY, SUNDAY):
            for hour in (0, 8, 10, 13, 15, 17, 23):
                moment = pkt(day, hour, 0)
                assert sessions.next_open(moment) > moment


class TestLegEnd:
    def test_returns_the_close_of_the_current_leg(self):
        assert sessions.leg_end(pkt(FRIDAY, 10, 0)) == pkt(FRIDAY, 12, 0)
        assert sessions.leg_end(pkt(FRIDAY, 15, 0)) == pkt(FRIDAY, 16, 30)
        assert sessions.leg_end(pkt(WEDNESDAY, 10, 0)) == pkt(WEDNESDAY, 15, 30)

    def test_returns_none_when_closed(self):
        """
        The collector's deadline is min(duration, leg_end). A None here means
        'no scheduled close', which only happens when the market is shut.
        """
        assert sessions.leg_end(pkt(FRIDAY, 13, 0)) is None
        assert sessions.leg_end(pkt(SATURDAY, 12, 0)) is None


def test_session_gap_sits_between_the_poll_interval_and_the_lunch_break():
    """
    SESSION_GAP_SECONDS splits observed snapshots into legs. It must be far
    above the 5-second poll interval so ordinary jitter never splits a session,
    and far below the 2h32m Friday lunch break so the break always does.
    """
    assert sessions.SESSION_GAP_SECONDS > 5 * 10
    friday_break = (
        datetime.combine(FRIDAY, time(14, 32))
        - datetime.combine(FRIDAY, time(12, 0))
    ).total_seconds()
    assert sessions.SESSION_GAP_SECONDS < friday_break


class TestHolidays:
    """The official PSX holiday calendar (v0.20.0): a holiday is a
    non-trading day no matter what weekday it falls on - the whole
    stack (collector, engine, EOD window, seatbelt) inherits the skip
    through legs_for()."""

    def test_known_weekday_holidays_have_no_legs(self):
        assert sessions.is_holiday(date(2026, 11, 9))   # Iqbal Day, Monday
        assert sessions.is_holiday(date(2026, 12, 25))  # Quaid-e-Azam, Friday
        assert not sessions.is_trading_day(date(2026, 11, 9))
        assert sessions.legs_for(date(2026, 11, 9)) == ()

    def test_adjacent_non_holiday_days_still_trade(self):
        # The days around Iqbal Day are ordinary trading days.
        assert sessions.is_trading_day(date(2026, 11, 6))   # Friday before
        assert sessions.is_trading_day(date(2026, 11, 10))  # Tuesday after

    def test_next_open_skips_a_holiday_monday(self):
        # From Friday Nov 6 after close, the next open must be Tuesday
        # Nov 10 (Monday Nov 9 is Iqbal Day), not Monday.
        fri_evening = datetime(2026, 11, 6, 17, 0, tzinfo=sessions.PKT)
        nxt = sessions.next_open(fri_evening)
        assert nxt.date() == date(2026, 11, 10)
        assert nxt.weekday() == 1  # Tuesday

    def test_repo_holidays_json_matches_code(self):
        import json
        from pathlib import Path
        data = json.loads(
            (Path(__file__).resolve().parents[1] / "data" / "psx_holidays.json")
            .read_text(encoding="utf-8")
        )
        listed = set(data["holidays"])
        # Every listed holiday must be recognized by the code...
        for iso in listed:
            assert sessions.is_holiday(date.fromisoformat(iso))
        # ...and the code must not know any date the file forgot.
        for day in sessions._HOLIDAYS:
            assert day in listed
