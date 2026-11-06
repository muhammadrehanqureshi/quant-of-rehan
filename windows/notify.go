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

// toastScript builds the PowerShell that raises a Windows toast. It uses the
// built in Windows Runtime notification API and the Windows PowerShell app id,
// so nothing has to be installed or registered. The text is XML escaped, which
// also removes every single quote, so it is safe inside the quoted XML string.
func toastScript(title, body string) string {
	xmlDoc := `<toast><visual><binding template="ToastGeneric"><text>` +
		xmlEscape(title) + `</text><text>` + xmlEscape(body) + `</text></binding></visual><audio silent="true"/></toast>`
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
