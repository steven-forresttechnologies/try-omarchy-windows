//go:build windows

package main

import (
	"runtime"
	"strings"
	"testing"
)

func TestHostArchUnsupportedReasonFor(t *testing.T) {
	tests := []struct {
		name        string
		processArch string
		native      uint16
		want        string
	}{
		{"native amd64", "amd64", imageFileMachineAmd64, ""},
		// Older Windows versions cannot report the native architecture; preserve
		// the existing amd64 fallback for those systems.
		{"unknown native architecture", "amd64", 0, ""},
		{"emulated amd64 on arm64", "amd64", imageFileMachineArm64, intelAMDOnlyMessage(uiText("arch.arm64_emulated"))},
		{"native arm64", "arm64", imageFileMachineArm64, intelAMDOnlyMessage(uiText("arch.arm64"))},
		{"arm64 with unknown native architecture", "arm64", 0, intelAMDOnlyMessage(uiText("arch.arm64"))},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := hostArchUnsupportedReasonFor(tt.processArch, tt.native); got != tt.want {
				t.Fatalf("hostArchUnsupportedReasonFor(%q, %#x) = %q, want %q", tt.processArch, tt.native, got, tt.want)
			}
		})
	}
}

// The machine the test runs on decides which branch applies: CI and real
// user hardware are x64-on-x64 (must run), ARM64 Windows gets the stop
// message. Either way, when a message is produced it must name the hardware
// that works and where to ask for an ARM64 build.
func TestHostArchUnsupportedReason(t *testing.T) {
	reason := hostArchUnsupportedReason()
	supported := runtime.GOARCH == "amd64" && nativeMachine() == imageFileMachineAmd64
	if supported && reason != "" {
		t.Fatalf("x64 launcher on x64 Windows should be supported, got: %q", reason)
	}
	if !supported && reason == "" && nativeMachine() != 0 {
		t.Fatal("non-x64 machine got no explanation")
	}
	if reason == "" {
		return
	}
	for _, want := range []string{"Intel", "AMD", "https://github.com/omacom/try-omarchy-windows"} {
		if !strings.Contains(reason, want) {
			t.Errorf("message should mention %q, got: %q", want, reason)
		}
	}
}
