//go:build !windows

package main

import "os/exec"

// sendToast is a best effort on non Windows hosts, used only for testing.
func sendToast(title, body string) {
	if p, err := exec.LookPath("notify-send"); err == nil {
		cmd := exec.Command(p, title, body)
		if cmd.Start() == nil {
			go func() { _ = cmd.Wait() }()
		}
	}
}

func openURL(u string) {
	if p, err := exec.LookPath("xdg-open"); err == nil {
		cmd := exec.Command(p, u)
		if cmd.Start() == nil {
			go func() { _ = cmd.Wait() }()
		}
	}
}

// playTone has no sound card to use here; the terminal bell stands in for it.
func playTone(steps []toneStep) {}

const toneNative = false
