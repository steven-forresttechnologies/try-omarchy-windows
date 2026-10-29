package main

import (
	"path/filepath"
	"strings"
	"testing"
)

func TestBuildQemuArgsForArmCPU(t *testing.T) {
	dir := t.TempDir()
	cfg := &config{vmDir: dir, guestDir: dir, disk: filepath.Join(dir, "disk.raw"),
		diskFormat: "raw", memMiB: 4096, cpus: 4, audio: "none"}
	args, err := buildQemuArgsForArch(cfg, "root=/dev/vda", "aarch64")
	if err != nil {
		t.Fatal(err)
	}
	joined := strings.Join(args, " ")
	for _, want := range []string{
		"-machine virt,accel=whpx -cpu host -smp 4 -m 4096M",
		"-device virtio-gpu-pci,id=gpu0", "-device virtio-keyboard-pci",
		"-device virtio-tablet-pci", "-device virtio-net-pci,netdev=n0,romfile=",
		"-device virtio-rng-pci", "-device virtio-sound-pci,audiodev=snd",
		"-kernel " + filepath.Join(dir, "vmlinuz-linux") + " -initrd " + filepath.Join(dir, "initramfs-linux.img"),
		"root=/dev/vda tryomarchy.render=cpu",
	} {
		if !strings.Contains(joined, want) {
			t.Errorf("ARM arguments missing %q: %s", want, joined)
		}
	}
	for _, forbidden := range []string{"q35", "qemu64", "ICH9-LPC", "-vga", "kernel-irqchip=off"} {
		if strings.Contains(joined, forbidden) {
			t.Errorf("ARM arguments contain x86-only option %q: %s", forbidden, joined)
		}
	}
}

func TestBuildQemuArgsForArchRejectsUnvalidatedModes(t *testing.T) {
	for _, tc := range []struct {
		name string
		arch string
		cfg  config
	}{
		{"unknown architecture", "arm64", config{}},
		{"ARM GPU", "aarch64", config{useGpu: true}},
		{"ARM Venus", "aarch64", config{venus: true}},
		{"ARM irqchip retry", "aarch64", config{irqchipOff: true}},
		{"ARM multiple displays", "aarch64", config{displays: 2}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			args, err := buildQemuArgsForArch(&tc.cfg, "", tc.arch)
			if err == nil || args != nil {
				t.Fatalf("got args %v, error %v; want rejection", args, err)
			}
		})
	}
}

func TestARMDevelopmentGPUTopologyAndCPURecovery(t *testing.T) {
	cfg := &config{useGpu: true, venus: true, arm64GPU: true, memMiB: 4096, cpus: 4}
	args, err := buildQemuArgsForArch(cfg, "root=/dev/vda", "aarch64")
	if err != nil {
		t.Fatal(err)
	}
	joined := strings.Join(args, " ")
	if !strings.Contains(joined, "virtio-gpu-gl-pci,blob=on,hostmem=268435456,venus=on") || strings.Contains(joined, "virtio-vga") {
		t.Fatalf("wrong ARM GPU topology: %s", joined)
	}
	cfg.useGpu = false
	args, err = buildQemuArgsForArch(cfg, "root=/dev/vda", "aarch64")
	if err != nil || !strings.Contains(strings.Join(args, " "), "virtio-gpu-pci,id=gpu0") {
		t.Fatalf("ARM GPU cannot recover to CPU: %v, %v", args, err)
	}
}

func TestARMPlaybackDoesNotAdvertiseDisabledCapture(t *testing.T) {
	cfg := &config{audio: "sdl"}
	cfg.desktop.MicrophoneDisabled = true
	args, err := buildQemuArgsForArch(cfg, "", "aarch64")
	if err != nil {
		t.Fatal(err)
	}
	joined := strings.Join(args, " ")
	for _, want := range []string{"virtio-sound-pci,audiodev=snd,streams=1", "in.voices=0"} {
		if !strings.Contains(joined, want) {
			t.Errorf("missing playback-only option %q: %s", want, joined)
		}
	}
	if strings.Contains(strings.Join(buildQemuArgs(cfg, ""), " "), "streams=1") {
		t.Fatal("ARM development changed the existing x86 device contract")
	}
}
