import unittest
from datetime import datetime, timedelta, timezone
import pandas as pd

from src.signals.intraday_engine import IntradaySignal, _five_minute, validate_signal

class TestIntradayEngine(unittest.TestCase):
    def test_target_is_exactly_two_percent(self):
        s=IntradaySignal("TEST","2026-10-07",100.0,102.0,0.8,0.7,1.0,0.5,True,True,False,"10:30")
        validate_signal(s)

    def test_one_minute_sequence_becomes_multiple_five_minute_bars(self):
        pkt=timezone(timedelta(hours=5))
        rows=[]
        start=datetime(2026,10,7,10,0,tzinfo=pkt)
        for i in range(15):
            t=start+timedelta(minutes=i)
            rows.append({"symbol":"TEST","bar_time":t,"open":100+i*.1,
                         "high":101+i*.1,"low":99+i*.1,"close":100.5+i*.1})
        out=_five_minute(pd.DataFrame(rows))
        self.assertGreaterEqual(len(out),3)
        self.assertEqual(out["symbol"].nunique(),1)

if __name__=="__main__":
    unittest.main()
