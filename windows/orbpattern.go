package main

import (
	"encoding/base64"
	"strings"
)

// The owner's orb is the dot matrix of
// windows/assets/orb-online-green-refined.gif. It was sampled from frame 0 at
// the GIF's own 55 by 50 grid: every dot keeps one of four brightness levels,
// so the console draws the picture itself instead of an approximation of its
// rings. hudInk applies the green or red palette at draw time.
const (
	orbCols = 55
	orbRows = 50

	orbPatternB64 = `AAAAAAAD//8AAAAAAAAAAAAAA//w//8AAAAAAAAAAAAAAAAAD/AAAAAAAAAAAAAD/8AA/AAAAAAAAAAADA//wwA8AAAAAAAAAAA8P/8MAA8AAAAAAPAMAAAA
AAAADwAAAAA8AwwA///8ADwPAAAAA8D8AP/////AwAPAAAAMD/A//AAA/wAPDwAAAMD/A/wAAAP/wD8AAAAPD/D/AD//wD8A/wAAAPAPD/A/AAD8D8D/AAAD
AAD8DwAAAA8PwPwAADw8D8DwD//8AwPA8AAAwDA8DAPwAP8DA8D8AA8AAPDAwAAADAMPw8AAMAADzA8AP8ADww/AAALAA8/w8A/z8A/DD8DDzgwPMw8DwAA8
DwwPDw8wDDz88DwAADwPDD8/DMAD/8PAwAAAPAww/PwzD88zDAwAAAAwPMDz8Mw/PMjwMAAAAMDwA8/D8PDzo8DAAAAAA8IPPw/Dw8wPAwAAAA4DCDwAMw/P
MjwMAAAAMAAD8PDMPz8MMDAAAADA8z/AAzDA/DDw8AAADwPM/wAMwADww8DwAAAwPDP8ADOAw8DDwPAADwDzD8ADzw8Pww8A/wPwDwz/MAwAAA8DDAAP8ADw
z/D8MAAAPwMPwAAADw8/wAPAAAA/Aw/wAAPw8/wADAAADDwDA/8/wA8/w/DwAADA/APAPPwDz/w/AwAAAAz8APwAA/D/w/w8AAAD/P8AD//8D/w/w8AAAAP8
PwAAAAP/APwMAAADw/w/w/////AwwMAAAA8D/AP////wAPAMAAAAAwDAwD///wAAA8AAAAADwA8AAAAA8AAAAAAAAAPAPADD/8DwAAAAAAAAAPAAAz//wAAA
AAAAAAAA/AAA/8AAAAAAAAAAAAAPwAAAAMAAAAAAAAAAAAP/8A//AAAAAAAAAAAAAAP//AAAAAAAAA==`
)

var orbLevels = decodeOrbPattern()

func decodeOrbPattern() []uint8 {
	raw, err := base64.StdEncoding.DecodeString(strings.ReplaceAll(orbPatternB64, "\n", ""))
	if err != nil || len(raw) < (orbCols*orbRows+3)/4 {
		return nil
	}
	levels := make([]uint8, orbCols*orbRows)
	for i := range levels {
		levels[i] = (raw[i/4] >> (6 - 2*(i%4))) & 3
	}
	return levels
}
