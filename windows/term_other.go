//go:build !windows && !linux

package main

import (
	"errors"
	"os"
)

type otherTerm struct{ keys chan Key }

func newTerm() Term { return &otherTerm{keys: make(chan Key)} }

func (t *otherTerm) Write(p []byte) (int, error) { return os.Stdout.Write(p) }
func (t *otherTerm) Init() error                 { return errors.New("this build supports Windows and Linux only") }
func (t *otherTerm) Restore()                    {}
func (t *otherTerm) Size() (int, int)            { return envSize() }
func (t *otherTerm) Keys() <-chan Key            { return t.keys }

const (
	mouseOnSeq  = ""
	mouseOffSeq = ""
)
