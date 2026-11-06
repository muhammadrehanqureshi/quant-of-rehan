//go:build windows

package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
)

// system32 gives the full path of a Windows system program, so a look alike
// earlier on PATH is never started by mistake.
func system32(parts ...string) string {
	root := os.Getenv("SystemRoot")
	if root == "" {
		root = `C:\Windows`
	}
	return filepath.Join(append([]string{root, "System32"}, parts...)...)
}

// sendToast raises a Windows notification without blocking the screen. The
// script goes to PowerShell on standard input, not as an encoded command and
// not with a bypassed policy, because those two switches are what security
// tools flag as malware behaviour. It still shows up in process logs as a
// hidden PowerShell start, so notifications can be turned off in Settings.
func sendToast(title, body string) {
	cmd := exec.Command(system32("WindowsPowerShell", "v1.0", "powershell.exe"),
		"-NoLogo", "-NoProfile", "-NonInteractive", "-Command", "-")
	cmd.Stdin = strings.NewReader(toastScript(title, body))
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000} // CREATE_NO_WINDOW
	if err := cmd.Start(); err != nil {
		return
	}
	go func() { _ = cmd.Wait() }()
}

var pBeep = kernel32.NewProc("Beep")

var toneBusy = make(chan struct{}, 1)

// playTone plays a short tone through the sound card. It runs on its own
// goroutine, and a tone that arrives while another is playing is dropped, so a
// burst of alerts is never a wall of noise.
func playTone(steps []toneStep) {
	select {
	case toneBusy <- struct{}{}:
	default:
		return
	}
	go func() {
		defer func() { <-toneBusy }()
		for _, st := range steps {
			pBeep.Call(uintptr(st.hz), uintptr(st.ms))
		}
	}()
}

// openURL opens an http or https link in the default browser.
func openURL(u string) {
	if !strings.HasPrefix(u, "https://") && !strings.HasPrefix(u, "http://") {
		return
	}
	cmd := exec.Command(system32("rundll32.exe"), "url.dll,FileProtocolHandler", u)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	if err := cmd.Start(); err == nil {
		go func() { _ = cmd.Wait() }()
	}
}

// toneNative is true where playTone makes a real sound.
const toneNative = true
