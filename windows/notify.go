package main

import (
	"encoding/xml"
	"strings"
)

// Titles for market events, taken from the app's string resources.
const (
	textMarketOpen   = "Market is open. Quant is online now."
	textMarketBreak  = "Market is on a break. Quant is offline until the market reopens."
	textMarketClosed = "Market is closed. Quant is sleeping now."
)

func marketEventTitle(ev string) string {
	switch ev {
	case "online":
		return textMarketOpen
	case "break":
		return textMarketBreak
	}
	return textMarketClosed
}

// Tones the app can play. Each is a list of (hertz, milliseconds) steps.
type toneStep struct{ hz, ms int }

var (
	toneBigBuy  = []toneStep{{784, 110}, {988, 110}, {1319, 190}} // rising, G5 B5 E6
	toneBigSell = []toneStep{{1319, 110}, {988, 110}, {659, 190}} // falling, E6 B5 E5
	toneEvent   = []toneStep{{880, 140}, {660, 180}}              // falling pair
	toneSignal  = []toneStep{{988, 100}, {1319, 100}, {1568, 100}, {1319, 100}, {1568, 220}}
)

func xmlEscape(s string) string {
	var b strings.Builder
	_ = xml.EscapeText(&b, []byte(s))
	return b.String()
}

// toastGlyphs turns the screen's symbols into plain ASCII for the toast. Owner
// report 2026-11-10: the change arrow reached the notification as "\u00d4\u00fb\u2593", because
// powershell.exe decodes its standard input as the system code page and the
// arrow's UTF-8 bytes were read as ANSI. The toast is raised by that script, so
// the notification text is folded to ASCII: a rising change is +, a falling one
// is -, the diamond and the separators become plain characters, and any other
// non-ASCII rune becomes a question mark rather than a broken glyph. The
// screen keeps its own arrows untouched.
var toastGlyphs = strings.NewReplacer(
	"\u25b2 ", "+", "\u25bc ", "-",
	"\u25b2", "+", "\u25bc", "-",
	"\u25c6 ", "", "\u25c6", "",
	"\u00b7", "-", "\u2026", "...",
	"\u2014", "-", "\u2013", "-", "\u2022", "*",
)

// asciiToast folds one line of toast text to ASCII, keeping the line breaks.
func asciiToast(s string) string {
	s = toastGlyphs.Replace(s)
	var b strings.Builder
	for _, r := range s {
		switch {
		case r == '\n' || r == '\r' || r == '\t':
			b.WriteRune(r)
		case r >= 32 && r < 127:
			b.WriteRune(r)
		case r > 127:
			b.WriteByte('?')
		}
	}
	return b.String()
}

// toastScript builds the PowerShell that raises a Windows toast. It uses the
// built in Windows Runtime notification API and the Windows PowerShell app id,
// so nothing has to be installed or registered. The text is XML escaped, which
// also removes every single quote, so it is safe inside the quoted XML string.
func toastScript(title, body string) string {
	// The toast text is ASCII before it is escaped, so the script that reads it
	// back cannot mis-decode a symbol (owner report 2026-11-10).
	xmlDoc := `<toast><visual><binding template="ToastGeneric"><text>` +
		xmlEscape(asciiToast(title)) + `</text><text>` + xmlEscape(asciiToast(body)) +
		`</text></binding></visual><audio silent="true"/></toast>`
	return strings.Join([]string{
		`$ErrorActionPreference = 'Stop'`,
		`[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null`,
		`[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null`,
		`$x = New-Object Windows.Data.Xml.Dom.XmlDocument`,
		`$x.LoadXml('` + xmlDoc + `')`,
		`$t = [Windows.UI.Notifications.ToastNotification]::new($x)`,
		`$id = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'`,
		`[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($id).Show($t)`,
	}, "\r\n")
}
