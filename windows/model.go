package main

import "time"

// appVersion mirrors the Android app this build is ported from.
const appVersion = "4.0.16"

// hudBuild is the build number of this Windows HUD port.
const hudBuild = "27"

// scripSearchHint is the same search line on every desktop search box.
const scripSearchHint = "Search for a KMIALL scrip"

// A terminal has one font size for the whole window, so the title is set in the
// theme's accent and closed by a diamond on either side. The owner asked for the
// diamonds close to the words, so there is one space inside each one; the glyph
// height is fixed by the console.
const headerTitle = "◆ QUANT OF REHAN ◆"

// headerTag is the index line under the title. Owner order 2026-11-07: the
// full line is back, INDEX included; build 18's shortened line is withdrawn.
// Owner order 2026-11-08 (build 25): the line keeps the build's own font, so
// build 23's small-capital letterforms are gone. A Windows console draws one
// glyph size per window, so the line is set in the same font, unbolded and in
// the soft ink, instead of being given a second typeface.
// Owner order 2026-11-08 (build 27): the font size is reduced again, so the
// small-capital line is back, the same words in the console's smallest
// letterforms. The plain text stays for the tests and the rest of the code.
const headerTag = "PSX'S KMIALL INDEX"

// headerTagSmall is the same eighteen cells set in Unicode small capitals, a
// size below the title without changing the console's single font size.
const headerTagSmall = "ᴘꜱx'ꜱ ᴋᴍɪᴀʟʟ ɪɴᴅᴇx"

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

// Quote is one row of the /prices table.
type Quote struct {
	Price     float64
	ChangePct *float64
	Buy       *int64
	Sell      *int64
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
