package main

import (
	"bytes"
	"compress/gzip"
	"testing"
)

func TestReadEODBarsKeepsTheYearAndRepairsTheEnvelope(t *testing.T) {
	const body = `date,symbol,open,high,low,close,volume
2025-11-07,PRL,100,101,99,100,500
2025-11-10,PRL,104,106,102,105,900
2026-10-05,PRL,120,119,118,121,500
2026-10-06,PRL,121,122,120,121,0
2026-11-09,PRL,130,131,129,130,500
2026-10-05,OGDC,200,201,199,200,500
`
	var buf bytes.Buffer
	zw := gzip.NewWriter(&buf)
	if _, err := zw.Write([]byte(body)); err != nil {
		t.Fatal(err)
	}
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
	zr, err := gzip.NewReader(bytes.NewReader(buf.Bytes()))
	if err != nil {
		t.Fatal(err)
	}
	defer zr.Close()
	bars, err := readEODBars(zr, "PRL")
	if err != nil {
		t.Fatal(err)
	}
	if len(bars) != 2 {
		t.Fatalf("PRL bars: %+v", bars)
	}
	if got := bars[0].At.Format("2006-01-02"); got != "2025-11-10" {
		t.Errorf("first bar is %s, want the first session inside the window", got)
	}
	if got := bars[1].High; got != 121 {
		t.Errorf("a ragged high was repaired to %v, want the row's own close 121", got)
	}
	if got := bars[1].Low; got != 118 {
		t.Errorf("a ragged low is %v, want 118", got)
	}
	if got := bars[1].Minute; got != "05 Oct 26" {
		t.Errorf("the daily label is %q", got)
	}
	if got := bars[1].Volume; got != 500 {
		t.Errorf("volume is %d, want 500", got)
	}
}
