package main

import "time"

// appVersion mirrors the Android app this build is ported from.
const appVersion = "4.0.20"

// hudBuild is the build number of this Windows HUD port. Owner order
// 2026-11-10: the bar and size build is 3.0.1, the toast encoding fix that
// follows it is 3.0.2, the return to build 21's bars is 3.0.3, the short
// centred bar that stays inside its own box is 3.0.4, the ten box flat bar
// with the price before it on the KSE100 tile is 3.0.5, the longer bar with the
// right aligned tile row is 3.0.6, the source orb, the new close times and the
// BUY= FLOW row are 3.0.7, the ten box bar, the left aligned ORDER FLOW
// headings and the bigger orb are 3.0.8, the signal SCORE, the longer box
// pitch and the aligned leader block are 3.0.9, the full dot face, the
// ten percent slower turn, the unbroken bars and MARKET OPENING are 3.0.38,
// the 3D orb return, the continuous centred bar rule and the KSE100 breadth
// thresholds are 3.2.3, TOP PERFORMERS, the symmetrical frame and the half
// speed globe are 3.2.4, the matching left tiles, the five eighths bars and the
// unsigned NET DELTA are 3.2.5, the separate SEARCH and SECTORS tiles, the blue
// cursors, the pre and post market times and the half block bars are 3.2.6, and
// the centred bars, the day's market times, the single diamond and the denser
// globe are 3.2.7, the lit globe and the taller bold bars are 3.2.8, the right
// aligned telemetry, the B/S/U FLOW row and the ALERTS LOG search are 3.2.9,
// and the restored 3.2.6 globe, the centred rectangle bars and the day's FLOW
// sides are 3.3.0, the seamless full-cell bars, the two scanner sorts, the
// VERSION before RELAY order and the leader PKR label are 3.3.1, the centred
// heavy-rule bars and the even 900 dot globe are 3.3.2, the KSE100 style
// CUSTOM SCRIPS OF VOLUME with its six sorts, the fifteen second LIVE window,
// the clock on the index line, the 15:49 and 16:49 close and the 100,000
// request tile are 3.3.3, the ten percent taller bold bar, the one column sort
// list and the trimmed RELAY and REQUESTS rows are 3.3.4, and the clock above
// the index line and the traded volume gate on TOP PERFORMERS are 3.3.5, and
// the one bar on every page, green for the buyers' share and red for the
// sellers', with the NET DELTA after it and in a column of its own on ORDER
// FLOW, is 3.3.6.
const hudBuild = "3.3.6"

// appVersionLabel is the version the SETTINGS page names. Owner order
// 2026-11-09: the page shows 2.8 alone, with no Windows build number and no
// ported app version beside it.
const appVersionLabel = hudBuild

// scripSearchHint is the same search line on every desktop search box.
const scripSearchHint = "Search for a KMIALL scrip"

// A terminal has one font size for the whole window, so the title is set in the
// theme's accent and closed by a diamond on either side. The owner asked for the
// diamonds close to the words, so there is one space inside each one; the glyph
// height is fixed by the console.
const headerTitle = "◆ QUANT OF REHAN ◆"

// headerTag is the index line under the title. Owner order 2026-11-09 (build
// 29): the line is in the same console font as the rest of the build, so the
// small-capital letterforms of build 27 are gone. A Windows console draws one
// glyph size per window, so this is the plain line, unbolded and in the soft
// ink, exactly like the other labels.
const headerTag = "PSX'S KMIALL INDEX"

// pkt is Pakistan time, fixed UTC+5 (no daylight saving), same as the session law.
var pkt = time.FixedZone("PKT", 5*3600)

// Leader is one of the top volume scrips the relay reports.
type Leader struct {
	Symbol      string
	Buy         *int64
	Sell        *int64
	Volume      *int64
	Price       *float64
	ChangePct   *float64
	SplitMethod string
}

func (l Leader) HasSplit() bool  { return l.Buy != nil && l.Sell != nil }
func (l Leader) HasVolume() bool { return l.Volume != nil }

// Market is the parsed /market answer (plus phase data from /health).
type Market struct {
	Answered            bool
	FeedHalted          bool
	FeedStatusFresh     bool
	IndexChange         *float64
	IndexPct            *float64
	IndexValue          *float64
	Open                bool
	Phase               string
	TransitionDelivered bool
	Date                string
	Condition           string
	ConditionText       string
	TradingDay          bool
	IndexAsOf           string
	IndexSource         string
	FeedStatus          string
	FeedStatusRaw       string
	FeedStatusAsOf      string
	TransitionState     string
	TransitionEvidence  string
	Leaders             []Leader
	Basis               string
	SplitBasis          string
	Note                string
	CacheAgeSeconds     int
	KarachiNow          string
	NextEvent           string
	Members             int
	WinLoss             *WinLoss
	QuoteSnapshotStale  bool
}

// WinLoss is the closed signal record the relay reports since app 3.6.0.
type WinLoss struct {
	Wins, Losses int
	Closed       *int
	RatePct      *int
}

func NewMarket() *Market {
	return &Market{TradingDay: true, FeedStatus: "UNKNOWN", CacheAgeSeconds: -1}
}

func (m *Market) HasIndex() bool {
	return m.IndexValue != nil && m.IndexChange != nil && m.IndexPct != nil
}

func (m *Market) PhaseKnown() bool { return m.Phase != "" }

func (m *Market) IsLive() bool { return m.Open && m.Phase != "BREAK" }

// Head is the parsed /health answer.
type Head struct {
	Reachable  bool
	MarketOpen bool
	Detail     string
	KarachiNow string
	NextEvent  string
	Phase      *Market
}

// Online is true only when the relay answers and a session is live.
func (h *Head) Online() bool { return h.Reachable && h.MarketOpen }

// Quote is one row of the /prices table, with the broker feed's traded total
// laid over it when the feed carries one.
type Quote struct {
	Price     float64
	ChangePct *float64
	Buy       *int64
	Sell      *int64
	// Volume is the traded total the scanner ranks a scrip by and draws as its
	// T. It is the measured buy and sell pair when the capture sided the row,
	// otherwise the broker feed's own volume.
	Volume *int64
}

// LiveQuote is one row of the /quotes broker feed.
type LiveQuote struct {
	Price      float64
	ChangePct  *float64
	Fresh      bool
	Change     *float64
	Volume     int64
	High, Low  float64
	Bid, Ask   float64
	AgeSeconds int // age at the moment the relay answered, -1 when unknown
	SourceTick string
	ObservedAt string
}

// RangeSplit is the relay's own buy and sell estimate: the share of the day's
// volume counted as buying is where the price sits inside the day's range.
// For KEL on 2026-10-30 (price 5.79, low 5.76, high 6.03, volume 21,471,271)
// it gives 2,385,697 bought, exactly what the relay reported.
func (q LiveQuote) RangeSplit() (buy, sell int64, ok bool) {
	if q.Volume <= 0 || q.High <= q.Low || q.Price < q.Low || q.Price > q.High {
		return 0, 0, false
	}
	frac := (q.Price - q.Low) / (q.High - q.Low)
	b := int64(float64(q.Volume) * frac)
	return b, q.Volume - b, true
}

// IndexQuote is the broker feed index reading.
type IndexQuote struct {
	Value     float64
	Change    float64
	ChangePct float64
	AsOf      string
	Fresh     bool
}

// Quotes is the parsed /quotes answer.
type Quotes struct {
	OK        bool
	Index     *IndexQuote
	Items     map[string]LiveQuote
	FetchedAt time.Time
}
