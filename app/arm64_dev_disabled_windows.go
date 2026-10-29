//go:build windows && !arm64dev

package main

import "os/exec"

func runARM64Development([]string) bool { return false }

func configureARM64DevelopmentQEMU(*exec.Cmd, bool) {}
