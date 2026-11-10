package main

import (
	"flag"
	"fmt"
	"image"
	"os"
	"os/signal"
	"path/filepath"
	"time"
)

func main() {
	mode := flag.String("mode", "both", "green, red, amber, or both (green and red side by side)")
	grow := flag.Float64("grow", OrbGrow, "ring scale against the app's orb (the default looks 10% bigger, see orb.go)")
	aspect := flag.Float64("aspect", defaultCellAspect, "cell height over cell width (9 by 20 pixels is 2.22)")
	out := flag.String("out", "", "write the GIF and PNG files of green and red into this folder and exit")
	scale := flag.Int("scale", 3, "pixel scale of the pictures written by -out")
	frames := flag.Int("frames", 160, "frames of the green GIF written by -out (160 at 0.1 s is the 16 s loop)")
	once := flag.Bool("ansi", false, "print one frame as colour text and exit")
	at := flag.Float64("t", 0, "seconds of motion of the frame printed by -ansi")
	flag.Parse()
	cellAspect = *aspect

	if *out != "" {
		if err := export(*out, *grow, *scale, *frames); err != nil {
			fmt.Fprintln(os.Stderr, "error:", err)
			os.Exit(1)
		}
		return
	}
	cols, rows := OrbCols(*grow), OrbRows(*grow)
	modes := map[string][]OrbMode{"green": {OrbGreen}, "red": {OrbRed}, "amber": {OrbAmber}, "both": {OrbGreen, OrbRed}}[*mode]
	if modes == nil {
		fmt.Fprintln(os.Stderr, "error: -mode must be green, red, amber or both")
		os.Exit(2)
	}
	const gap = 2
	w := len(modes)*cols + (len(modes)-1)*gap
	draw := func(t float64) *Canvas {
		c := NewCanvas(w, rows, DefaultStyle().BG)
		for i, m := range modes {
			DrawOrbSized(c, i*(cols+gap), 0, cols, rows, t, m, *grow)
		}
		return c
	}
	if *once {
		fmt.Print(draw(*at).ANSI())
		return
	}
	live(draw, w, rows)
}

// live animates the orbs in the terminal at 10 frames a second until Ctrl+C.
func live(draw func(t float64) *Canvas, w, rows int) {
	enableVT()
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt)
	fmt.Print("\x1b[?25l\x1b[2J") // hide the cursor, clear the screen
	defer fmt.Print("\x1b[0m\x1b[?25h\r\n")
	tick := time.NewTicker(100 * time.Millisecond)
	defer tick.Stop()
	start := time.Now()
	for {
		fmt.Print("\x1b[H" + draw(time.Since(start).Seconds()).ANSI())
		select {
		case <-stop:
			return
		case <-tick.C:
		}
	}
}

// export writes QoR-orb-green.gif, QoR-orb-red.gif and a PNG of each into dir.
func export(dir string, grow float64, scale, frames int) error {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	st := DefaultStyle()
	st.Scale = scale
	cols, rows := OrbCols(grow), OrbRows(grow)
	one := func(mode OrbMode, t float64) *Canvas {
		c := NewCanvas(cols, rows, st.BG)
		DrawOrbSized(c, 0, 0, cols, rows, t, mode, grow)
		return c
	}
	save := func(name string, fn func(f *os.File) error) error {
		f, err := os.Create(filepath.Join(dir, name))
		if err != nil {
			return err
		}
		if err := fn(f); err != nil {
			f.Close()
			return err
		}
		return f.Close()
	}
	// Green turns: 0.1 s a frame, and 160 frames is exactly one 16 s loop. The picture
	// is centred on the box round every dot the orb lights over the whole loop, so
	// the orb does not wander in the frame and green and red sit the same way.
	cs := make([]*Canvas, frames)
	for i := range cs {
		cs[i] = one(OrbGreen, float64(i)*0.1)
	}
	st = st.Centre(cs...)
	var fs []*image.Paletted
	for i := 0; i < frames; i++ {
		f, err := st.Paletted(cs[i], radarPalette(OrbGreen))
		if err != nil {
			return err
		}
		fs = append(fs, f)
	}
	if err := save("QoR-orb-green.gif", func(f *os.File) error { return WriteGIF(f, fs, 10) }); err != nil {
		return err
	}
	// Red does not move, so it is one frame, centred on its own dots.
	redCanvas := one(OrbRed, 0)
	rst := st.Centre(redCanvas)
	red, err := rst.Paletted(redCanvas, radarPalette(OrbRed))
	if err != nil {
		return err
	}
	if err := save("QoR-orb-red.gif", func(f *os.File) error { return WriteGIF(f, []*image.Paletted{red}, 40) }); err != nil {
		return err
	}
	// A PNG of each at full colour: green as it is at 0 s, red as it rests.
	pngs := []struct {
		mode OrbMode
		c    *Canvas
		st   Style
	}{{OrbGreen, cs[0], st}, {OrbRed, redCanvas, rst}}
	for _, p := range pngs {
		img, err := p.st.RGBA(p.c)
		if err != nil {
			return err
		}
		if err := save("QoR-orb-"+p.mode.String()+".png", func(f *os.File) error { return WritePNG(f, img) }); err != nil {
			return err
		}
	}
	fmt.Printf("wrote %d green frames, the red orb and a PNG of each into %s (%d by %d cells, orb %.0f%% of the app's size)\n",
		len(fs), dir, cols, rows, grow*100)
	return nil
}
