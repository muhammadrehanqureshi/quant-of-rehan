# The 100 strategies

All long only, all built for the PSX KMIALL universe (trade the constituent stocks, use the KMIALL index as market context).
A signal is read at the close of a bar and the trade enters at the next bar's open. Every strategy runs on 5m, 15m, 30m, 1h and 1d
unless its row says otherwise. Strategies marked [index] need the KMIALL series in the data folder and are skipped without it.

Default maximum hold in bars per timeframe: 5m 36, 15m 24, 30m 14, 1h 7, 1d 5. Intraday trades are flat by the last bar of the session unless the row says it holds overnight.

## Trend following (16)

### S001 EMA 9/21 cross in an EMA200 uptrend
- trigger: EMA9 crosses above EMA21
- filter: close above EMA200
- base parameters {"f": 9, "s": 21, "t": 200}, 2 variant(s) with --grid

### S002 EMA 20/50 cross with a strengthening ADX
- trigger: EMA20 crosses above EMA50
- filter: ADX14 above 20 and rising
- base parameters {"a": 20, "f": 20, "s": 50}, 2 variant(s) with --grid

### S003 Bounce off EMA21 inside an 8/21/55 EMA stack
- filter: EMA8 > EMA21 > EMA55
- trigger: low tags EMA21 and the bar closes green above it
- base parameters {"a": 8, "b": 21, "c": 55}, 1 variant(s) with --grid

### S004 Golden cross SMA50 over SMA200 [1h 1d]
- trigger: SMA50 crosses above SMA200
- base parameters {"f": 50, "s": 200}, 1 variant(s) with --grid

### S005 Supertrend 10/3 flips up
- trigger: Supertrend(10, 3) turns from down to up
- base parameters {"m": 3.0, "n": 10}, 2 variant(s) with --grid

### S006 Supertrend flip confirmed by a rising EMA50
- trigger: Supertrend flips up
- filter: EMA50 rising and close above it
- base parameters {"m": 3.0, "n": 10}, 1 variant(s) with --grid

### S007 Donchian 20 breakout on volume
- trigger: close above the prior 20 bar high
- filter: volume 1.2x its 20 bar average
- base parameters {"n": 20, "vm": 1.2}, 2 variant(s) with --grid

### S008 Turtle 55 breakout with expanding ATR
- trigger: close above the prior 55 bar high
- filter: ATR14 above its 50 bar average
- base parameters {"n": 55}, 2 variant(s) with --grid

### S009 Ichimoku cloud breakout with Tenkan over Kijun
- trigger: close crosses above the cloud top
- filter: Tenkan above Kijun
- base parameters {}, 0 variant(s) with --grid

### S010 Parabolic SAR flips up with ADX above 20
- trigger: PSAR turns from above price to below
- filter: ADX14 above 20
- base parameters {"a": 20}, 2 variant(s) with --grid

### S011 MACD signal cross above zero in an EMA100 uptrend
- trigger: MACD line crosses above signal
- filter: MACD above zero and close above EMA100
- base parameters {"f": 12, "g": 9, "s": 26, "t": 100}, 1 variant(s) with --grid

### S012 MACD histogram turns up in an uptrend
- trigger: histogram stops falling while still below zero
- filter: close above EMA100
- base parameters {"t": 100}, 1 variant(s) with --grid

### S013 Aroon 25 up line crosses the down line
- trigger: Aroon up crosses above Aroon down
- filter: Aroon up above 70
- base parameters {"lv": 70, "n": 25}, 2 variant(s) with --grid

### S014 Vortex 14 cross with trend strength
- trigger: VI+ crosses above VI-
- filter: ADX14 above 18
- base parameters {"a": 18, "n": 14}, 1 variant(s) with --grid

### S015 Hull MA 21 turns up
- trigger: HMA slope flips from down to up
- filter: close above the HMA
- base parameters {"n": 21}, 2 variant(s) with --grid

### S016 Clean regression uptrend starts
- state: 30 bar regression slope positive with R squared above 0.6
- filter: close above the fitted line
- base parameters {"n": 30, "r2": 0.6}, 2 variant(s) with --grid

## Pullback in an uptrend (18)

### S017 Connors RSI(2) below 10 above SMA200
- trigger: RSI2 below 10
- filter: close above SMA200
- base parameters {"n": 2, "th": 10}, 2 variant(s) with --grid

### S018 RSI14 recovers through 40 inside an EMA50 over EMA200 trend
- trigger: RSI14 crosses above 40
- filter: EMA50 above EMA200
- base parameters {"th": 40}, 2 variant(s) with --grid

### S019 Bollinger lower band reclaim in an uptrend
- trigger: close crosses back above the lower band (20, 2)
- filter: close above SMA100
- base parameters {"k": 2.0, "n": 20}, 2 variant(s) with --grid

### S020 Keltner lower channel reclaim
- trigger: close crosses back above EMA20 minus 2 ATR10
- filter: close above EMA200
- base parameters {"m": 2.0}, 2 variant(s) with --grid

### S021 Z-score snap back from minus 2
- trigger: yesterday z(20) below -2 and z turns up
- filter: close above SMA200
- base parameters {"n": 20, "z": -2.0}, 2 variant(s) with --grid

### S022 Stochastic oversold cross in an uptrend
- trigger: %K crosses above %D from below 20
- filter: close above EMA100
- base parameters {"lv": 20}, 2 variant(s) with --grid

### S023 Williams %R leaves oversold in an uptrend
- trigger: %R(14) crosses above -80
- filter: EMA50 above EMA200
- base parameters {"lv": -80}, 1 variant(s) with --grid

### S024 CCI recovers through minus 100 in an uptrend
- trigger: CCI20 crosses above -100
- filter: EMA50 above EMA200
- base parameters {"lv": -100}, 1 variant(s) with --grid

### S025 Internal bar strength washout above SMA200
- trigger: close in the bottom 20 percent of the bar range
- filter: close above SMA200
- base parameters {"th": 0.2}, 2 variant(s) with --grid

### S026 Three down closes then a green bar in an uptrend
- setup: three consecutive lower closes
- trigger: next bar closes green
- filter: close above EMA200
- base parameters {"t": 200}, 1 variant(s) with --grid

### S027 VWAP dip and reclaim on high volume [5m 15m 30m 1h]
- setup: price dipped 0.5 ATR below the day VWAP in the last 6 bars
- trigger: close crosses back above VWAP
- base parameters {"d": 0.5}, 2 variant(s) with --grid

### S028 Fibonacci 50 to 61.8 percent pullback bounce
- setup: 40 bar up leg wider than 2 ATR
- trigger: bullish bar closing in the 50 to 61.8 percent retracement zone
- base parameters {"n": 40}, 2 variant(s) with --grid

### S029 Gap down that reverses above the first bar high [5m 15m 30m 1h]
- setup: gap down more than 1 percent
- trigger: close above the day open and above the first bar high
- base parameters {"g": -0.01}, 2 variant(s) with --grid

### S030 MFI leaves oversold in an uptrend
- trigger: MFI14 crosses above 20
- filter: close above EMA100
- base parameters {"lv": 20}, 1 variant(s) with --grid

### S031 EMA20 tag followed by a bullish engulfing bar
- setup: previous bar tagged EMA20 in an EMA20 > EMA50 trend
- trigger: bullish engulfing
- base parameters {}, 0 variant(s) with --grid

### S032 RSI5 washout on rising volume
- trigger: RSI5 below 20 with volume above the previous bar
- filter: close above EMA100
- base parameters {"th": 20}, 2 variant(s) with --grid

### S033 Shallow ATR pullback in an EMA50 uptrend
- setup: close 1 to 2 ATR under the 20 bar high with ATR5 below ATR14
- trigger: green bar above EMA50
- base parameters {"hi": 2.0, "lo": 1.0}, 1 variant(s) with --grid

### S034 Two bar reversal at the lower Bollinger band
- setup: red bar tagged the lower band
- trigger: green bar closing above the red bar high
- base parameters {}, 0 variant(s) with --grid

## Breakout and volatility (16)

### S035 Bollinger squeeze release upwards
- setup: band width within 10 percent of its 120 bar minimum in the last 5 bars
- trigger: close above the upper band
- base parameters {"n": 20}, 1 variant(s) with --grid

### S036 NR7 narrow range breakout
- setup: previous bar had the narrowest range of 7
- trigger: close above that bar high
- base parameters {"n": 7}, 2 variant(s) with --grid

### S037 Inside bar breakout above the mother bar
- setup: previous bar inside the bar before it
- trigger: close above the mother bar high
- filter: EMA20 rising
- base parameters {}, 0 variant(s) with --grid

### S038 ATR expansion bar closing near its high
- trigger: true range above 1.5 times the prior ATR14
- filter: close in the top quarter of the bar and above EMA20
- base parameters {"m": 1.5}, 2 variant(s) with --grid

### S039 Opening range breakout, 30 minutes [5m 15m 30m 1h]
- trigger: first close above the 30 minute opening range high
- filter: volume above its 20 bar average
- base parameters {"mins": 30}, 2 variant(s) with --grid

### S040 Opening range breakout, 60 minutes, with VWAP and a flat or up open [5m 15m 30m 1h]
- trigger: first close above the 60 minute opening range high
- filter: close above VWAP, gap not negative
- base parameters {"mins": 60}, 1 variant(s) with --grid

### S041 Previous day high breakout above VWAP [5m 15m 30m 1h]
- trigger: close crosses above yesterday's high
- filter: close above VWAP
- base parameters {}, 0 variant(s) with --grid

### S042 Gap up that holds its open [5m 15m 30m 1h]
- setup: gap up above 1 percent, never traded 0.5 percent under the open
- trigger: first close after 15 minutes above open and VWAP
- base parameters {"g": 0.01}, 2 variant(s) with --grid

### S043 Volume spike breakout
- trigger: close above the prior 20 bar high
- filter: volume above 3 times its average
- base parameters {"n": 20, "vm": 3.0}, 2 variant(s) with --grid

### S044 One year closing high [1h 1d]
- trigger: close above the highest close of the last 250 sessions
- base parameters {"days": 250}, 1 variant(s) with --grid

### S045 Range expansion day closing above the prior high
- trigger: range above 2 times its 20 bar average, green, close above the prior high
- base parameters {"m": 2.0}, 1 variant(s) with --grid

### S046 Volatility contraction pattern breakout
- setup: ATR5 under 0.8 times ATR50 for 3 bars
- trigger: close above the prior 10 bar high
- base parameters {"k": 3, "r": 0.8}, 2 variant(s) with --grid

### S047 Break of the last confirmed swing high
- setup: pivot high confirmed after 3 lower bars
- trigger: close crosses above the pivot
- filter: close above EMA50
- base parameters {}, 0 variant(s) with --grid

### S048 Keltner channel breakout with ADX and volume
- trigger: close above EMA20 plus 2 ATR10
- filter: ADX14 above 20 and rising, volume above average
- base parameters {"m": 2.0}, 2 variant(s) with --grid

### S049 Darvas style tight box breakout
- setup: prior 20 bar box under 6 ATR tall
- trigger: close above the box top on 1.2 times volume
- base parameters {"h": 6.0}, 2 variant(s) with --grid

### S050 Five bar high breakout in an EMA20 uptrend [1h 1d]
- trigger: close above the prior 5 bar high
- filter: close above EMA20 and volume above average
- base parameters {"n": 5}, 2 variant(s) with --grid

## Candlestick pattern (10)

### S051 Bullish engulfing at a 20 bar low after a decline
- setup: prior bar within 1 percent of the 20 bar low, close under the close 4 bars before
- trigger: bullish engulfing
- base parameters {}, 0 variant(s) with --grid

### S052 Hammer under the lower Bollinger band
- trigger: long lower wick (2x the body), small upper wick
- setup: low pierces the lower band (20, 2)
- base parameters {}, 0 variant(s) with --grid

### S053 Morning star
- bar 1: big red body
- bar 2: small body under bar 1 close
- bar 3: green close past the middle of bar 1
- base parameters {}, 0 variant(s) with --grid

### S054 Three white soldiers
- three green bars with rising closes
- each body above 60 percent of its range
- each open inside or at the edge of the prior body
- base parameters {}, 0 variant(s) with --grid

### S055 Piercing line
- prior big red bar
- green bar opens under its close and closes above its midpoint but below its open
- base parameters {}, 0 variant(s) with --grid

### S056 Tweezer bottom
- red bar then green bar with matching lows (within 0.1 ATR)
- base parameters {"t": 0.1}, 1 variant(s) with --grid

### S057 Bullish marubozu on volume above EMA50
- body at least 90 percent of the range, green
- volume above 1.5 times average, close above EMA50
- base parameters {"vm": 1.5}, 1 variant(s) with --grid

### S058 Bullish harami after weakness
- prior big red bar
- small green bar inside its body
- RSI14 below 40 on the prior bar
- base parameters {"r": 40}, 1 variant(s) with --grid

### S059 Dragonfly doji at a 20 bar low
- tiny body, long lower wick, almost no upper wick
- low at or under the prior 20 bar low
- base parameters {}, 0 variant(s) with --grid

### S060 Rising three methods
- big green bar
- three small bars inside its range
- green close above its high
- base parameters {}, 0 variant(s) with --grid

## Volume and money flow (10)

### S061 OBV leads a 10 bar closing high
- trigger: OBV above its prior 20 bar high
- confirm: close above the prior 10 bar closing high
- base parameters {}, 0 variant(s) with --grid

### S062 Chaikin money flow crosses 0.1 above EMA50
- trigger: CMF20 crosses above 0.1 and is rising
- filter: close above EMA50
- base parameters {"lv": 0.1}, 2 variant(s) with --grid

### S063 Three bar accumulation run
- three higher closes
- three rising volumes
- close above EMA20
- base parameters {}, 0 variant(s) with --grid

### S064 VWAP reclaim on strong volume [5m 15m 30m 1h]
- trigger: close crosses above the day VWAP
- filter: volume 1.5 times average, not in the first 3 bars
- base parameters {"vm": 1.5}, 2 variant(s) with --grid

### S065 Accumulation distribution divergence at a new low
- setup: close makes a new 20 bar low while the A/D line holds above its own 20 bar low
- trigger: green bar
- base parameters {}, 0 variant(s) with --grid

### S066 Volume dry up then expansion
- setup: 3 bars under half the average volume
- trigger: green bar on 2 times volume closing higher
- base parameters {"dry": 0.5, "ex": 2.0}, 1 variant(s) with --grid

### S067 MFI crosses 50 above EMA20
- trigger: MFI14 crosses above 50
- filter: close above EMA20
- base parameters {"lv": 50}, 1 variant(s) with --grid

### S068 Force index crosses zero in an EMA20 over EMA50 trend
- trigger: force index(13) crosses above zero
- filter: EMA20 above EMA50
- base parameters {}, 0 variant(s) with --grid

### S069 Ease of movement turns positive above EMA50
- trigger: EOM14 crosses above zero
- filter: close above EMA50
- base parameters {}, 0 variant(s) with --grid

### S070 Selling climax reversal
- setup: volume above 3 times average, RSI14 under 30 in the last 3 bars
- trigger: green bar closing in the upper half
- base parameters {"vm": 3.0}, 1 variant(s) with --grid

## Intraday session (8)

### S071 Opening drive continuation [5m 15m 30m 1h]
- setup: up more than 0.5 percent from the open after 30 minutes
- trigger: first such close above VWAP on above average volume
- base parameters {"r": 0.005}, 2 variant(s) with --grid

### S072 Gap up VWAP dip then reclaim [5m 15m 30m 1h]
- setup: gap up above 0.5 percent, price traded under VWAP
- trigger: first close back above VWAP
- base parameters {"g": 0.005}, 2 variant(s) with --grid

### S073 Midday compression breakout [5m 15m 30m]
- setup: prior hour range under 2.5 ATR
- trigger: close above the prior hour high between minute 90 and 300
- base parameters {"m": 2.5}, 2 variant(s) with --grid

### S074 Late session strength held overnight [overnight] [5m 15m 30m 1h]
- setup: after minute 240, close in the top 20 percent of the day range, up 0.5 percent, above VWAP
- exit: TP, SL or the next session
- base parameters {"r": 0.005}, 1 variant(s) with --grid

### S075 Yesterday close reclaim after a morning dip [5m 15m 30m 1h]
- setup: traded more than 1 percent under yesterday's close
- trigger: first close back above it
- base parameters {"d": 0.01}, 2 variant(s) with --grid

### S076 Day open reclaim on volume [5m 15m 30m 1h]
- setup: traded 0.5 percent under the day open
- trigger: first close back above the open on above average volume
- base parameters {"d": 0.005}, 2 variant(s) with --grid

### S077 Strong yesterday plus opening range break [5m 15m 30m 1h]
- setup: yesterday closed in the top quarter of its range
- trigger: first close above today's 30 minute opening range high
- base parameters {}, 0 variant(s) with --grid

### S078 Failed opening range breakdown (bear trap) [5m 15m 30m 1h]
- setup: close under the 30 minute opening range low within the last 3 bars
- trigger: green close back above that low
- base parameters {}, 0 variant(s) with --grid

## Market index and relative strength (8)

### S079 Relative strength breakout while the index trends up [index]
- market: KMIALL above its EMA50
- stock: outperforming the index over 20 bars and rising
- trigger: close above the prior 20 bar high
- base parameters {"n": 20}, 1 variant(s) with --grid

### S080 Index oversold bounce, strong stock [index]
- market: KMIALL RSI2 under 10
- stock: close above its SMA200
- base parameters {"th": 10}, 2 variant(s) with --grid

### S081 Stock rises on volume while the index falls [index]
- market: index bar down
- stock: up 0.3 percent on 1.2 times volume above EMA20
- base parameters {"r": 0.003}, 2 variant(s) with --grid

### S082 Relative strength line at a 60 bar high [index]
- stock to index ratio above its prior 60 bar high
- market: KMIALL above its EMA50
- base parameters {"n": 60}, 1 variant(s) with --grid

### S083 Excess return over the index in ATR units [index]
- 10 bar return minus the index return above 2 ATR units and rising
- close above EMA20
- base parameters {"z": 2.0}, 2 variant(s) with --grid

### S084 Strong stock buys an index pullback [index]
- market: KMIALL under EMA20 but above EMA100
- stock: above EMA20, green, relative strength rising
- base parameters {}, 0 variant(s) with --grid

### S085 Follow an index 20 bar breakout [index]
- market: KMIALL closes above its prior 20 bar high
- stock: above EMA20 and up on the bar
- base parameters {"n": 20}, 1 variant(s) with --grid

### S086 EMA20 pullback in a calm index regime [index]
- market: KMIALL ATR% under its 100 bar average
- stock: EMA20 > EMA50, low tags EMA20, green close above it
- base parameters {}, 0 variant(s) with --grid

## Calendar (4)

### S087 Turn of the month window above EMA50 [1d]
- window: calendar day 28 onwards or the first 3 trading days of a month
- filter: close above EMA50
- base parameters {}, 0 variant(s) with --grid

### S088 Quarter end window dressing [1d]
- window: March, June, September or December from day 26
- filter: close above EMA20 and 20 day return positive
- base parameters {}, 0 variant(s) with --grid

### S089 Thursday close drift into Friday [1d]
- setup: Thursday green close above EMA20
- exit: Friday
- base parameters {}, 0 variant(s) with --grid

### S090 Monday reversal after a weak Friday [1d]
- setup: Friday fell more than 1.5 percent
- trigger: Monday closes green
- base parameters {"d": -0.015}, 2 variant(s) with --grid

## Composite and multi timeframe (10)

### S091 Kalman trend flip (analogue of the current QoR baseline)
- filter: local linear trend Kalman filter on log price
- trigger: slope crosses above a small positive threshold
- base parameters {"hy": 0.05, "snr": 0.02}, 2 variant(s) with --grid
- note: Baseline. QoR's live Kalman flip lost all three of its first signals, so this is the bar to beat.

### S092 Kalman flip with volume and VWAP or EMA20
- trigger: Kalman slope positive and rising, close above the filter
- filter: volume above average, above VWAP (intraday) or EMA20 (daily)
- base parameters {"snr": 0.02}, 1 variant(s) with --grid

### S093 Heikin Ashi: three green bars with no lower wick
- setup: red Heikin Ashi bar
- trigger: three green Heikin Ashi bars with no lower shadow
- base parameters {}, 0 variant(s) with --grid

### S094 Elder triple screen
- slow screen: higher timeframe MACD histogram rising
- fast screen: Stochastic %K crosses %D from under 30
- base parameters {"lv": 30}, 1 variant(s) with --grid

### S095 Squeeze release with rising momentum
- setup: Bollinger bands inside Keltner channel, then released
- trigger: momentum above zero and rising
- base parameters {}, 0 variant(s) with --grid

### S096 ConnorsRSI washout above SMA200
- composite: RSI3, RSI2 of the up/down streak, 100 bar percent rank of the 1 bar return
- trigger: average under 10
- filter: close above SMA200
- base parameters {"th": 10}, 2 variant(s) with --grid

### S097 Schaff trend cycle crosses 25
- trigger: STC(23, 50, 10) crosses above 25
- filter: close above EMA100
- base parameters {"lv": 25}, 1 variant(s) with --grid

### S098 Three of four vote: trend, momentum, volume, RSI band
- votes: EMA20 > EMA50, 10 bar return > 0, volume above average, RSI14 between 50 and 70
- trigger: votes reach 3
- base parameters {"k": 3}, 1 variant(s) with --grid

### S099 Higher timeframe uptrend, RSI5 pullback recovery
- filter: higher timeframe EMA20 above EMA50
- trigger: RSI5 crosses back above 30
- base parameters {"lv": 30}, 2 variant(s) with --grid

### S100 Higher timeframe uptrend plus Donchian 20 breakout
- filter: higher timeframe EMA20 above EMA50
- trigger: close above the prior 20 bar high on 1.2 times volume
- base parameters {"n": 20}, 2 variant(s) with --grid

