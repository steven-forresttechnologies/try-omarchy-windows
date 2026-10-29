//go:build windows && arm64dev

package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"
	"unsafe"
)

func configureARM64DevelopmentQEMU(cmd *exec.Cmd, gpu bool) {
	// SDL loads graphics backends dynamically. A developer PATH can contain
	// incompatible EGL/GLES DLLs from another application. Keep both the
	// working directory and DLL search path inside the verified runtime and
	// Windows; CPU mode needs only SDL's software display backend.
	cmd.Dir = filepath.Dir(cmd.Path)
	env := make([]string, 0, len(cmd.Env)+2)
	for _, item := range cmd.Env {
		key, _, _ := strings.Cut(item, "=")
		if strings.HasPrefix(strings.ToUpper(key), "VK_") {
			continue
		}
		switch strings.ToUpper(key) {
		case "PATH", "SDL_RENDER_DRIVER", "SDL_OPENGL_LIBRARY", "SDL_VIDEO_GL_DRIVER", "SDL_VIDEO_EGL_DRIVER",
			"WINQ_DMABUF_SHIM_OFF":
			continue
		}
		env = append(env, item)
	}
	windows := os.Getenv("SystemRoot")
	cmd.Env = append(env, "PATH="+filepath.Join(windows, "System32")+";"+windows)
	if gpu {
		cmd.Env = append(cmd.Env, "VK_DRIVER_FILES="+filepath.Join(cmd.Dir, "dzn-arm64.json"),
			"VK_LOADER_LAYERS_DISABLE=~implicit~", "WINQ_DMABUF_SHIM_OFF=1")
	} else {
		cmd.Env = append(cmd.Env, "SDL_RENDER_DRIVER=software")
	}
}

func runARM64Development(arguments []string) bool {
	if len(arguments) == 0 || arguments[0] != "-arm64-dev" {
		return false
	}
	if err := launchARM64Development(arguments[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "ARM64 development:", err)
		os.Exit(1)
	}
	return true
}

func launchARM64Development(arguments []string) error {
	flags := flag.NewFlagSet("arm64-dev", flag.ContinueOnError)
	dir := flags.String("dir", "", "new, isolated ARM development installation directory")
	guest := flags.String("guest", "", "local aarch64 guest artifacts directory")
	archive := flags.String("runtime", "", "local ARM64 runtime ZIP")
	guestHash := flags.String("guest-sha256", "", "independent SHA256 of guest SHA256SUMS")
	runtimeHash := flags.String("runtime-sha256", "", "independent SHA256 of runtime ZIP")
	instant := flags.Bool("instant", false, "use the guest quick-start account")
	cpus := flags.Int("cpus", 4, "guest CPUs (1 to 16)")
	memory := flags.Int("memory", 4096, "guest RAM in MiB (2048 to 32768)")
	audio := flags.Bool("audio", false, "enable SDL playback (microphone remains disabled)")
	exchange := flags.Bool("exchange", false, "share this installation's exchange folder with the guest")
	gpu := flags.Bool("gpu", false, "use the verified private Dozen ICD and shared-memory Venus presentation")
	fullscreen := flags.Bool("fullscreen", false, "start on the primary display in fullscreen mode")
	shutdownAfter := flags.Duration("shutdown-after", 0, "development test: request poweroff after this time at userspace readiness")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("unexpected ARM development arguments")
	}
	if runtime.GOARCH != "arm64" || nativeMachine() != imageFileMachineArm64 {
		return fmt.Errorf("requires a native ARM64 launcher and ARM64 Windows")
	}
	if *cpus < 1 || *cpus > 16 || *memory < 2048 || *memory > 32768 {
		return fmt.Errorf("invalid ARM development resources")
	}
	if *shutdownAfter < 0 || *shutdownAfter > 10*time.Minute {
		return fmt.Errorf("invalid test shutdown interval")
	}
	if !whpPresent() {
		return fmt.Errorf("Windows Hypervisor Platform is unavailable")
	}
	var features uint64
	var written uint32
	hr, _, _ := procWHvGetCapability.Call(1, uintptr(unsafe.Pointer(&features)), 8, uintptr(unsafe.Pointer(&written)))
	if hr != 0 || written < 8 || features&(1<<11) == 0 {
		return fmt.Errorf("WHP does not report ARM64 support")
	}
	pins := armDevelopmentPins{GuestManifest: normalizedSHA256(*guestHash), RuntimeArchive: normalizedSHA256(*runtimeHash)}
	if err := validateARMDevelopmentPins(pins); err != nil {
		return err
	}
	for _, path := range []string{*dir, *guest, *archive} {
		if _, err := armDevelopmentPath(path); err != nil {
			return err
		}
	}
	// The ordinary single-VM guard also prevents a second process from using
	// the same mutable disk while artifact verification is in progress.
	runLifecycleListener()
	configureSetupCancellation(false)
	defer uiDone()
	if err := prepareARMDevelopment(*dir, *guest, *archive, pins); err != nil {
		return err
	}
	cfg := &config{
		dir: *dir, hostDir: *dir, guestDir: filepath.Join(*dir, "guest"), vmDir: filepath.Join(*dir, "vm"),
		disk: filepath.Join(*dir, "vm", "disk.qcow2"), diskFormat: "qcow2",
		qemu:              filepath.Join(*dir, "runtime", "bin", "qemu-system-aarch64w.exe"),
		guestArchitecture: "aarch64", runtimeID: pins.RuntimeArchive,
		cpus: *cpus, memMiB: *memory, displays: 1, displayWidth: 1280, displayHeight: 800,
		renderMode: "cpu", audio: "none", instant: *instant, disablePinch: true,
		fullscreen: *fullscreen,
	}
	cfg.desktop.MicrophoneDisabled = true
	cfg.desktop.CameraDisabled = true
	if *gpu {
		if err := verifyARMDevelopmentGraphics(filepath.Join(*dir, "runtime")); err != nil {
			return err
		}
		cfg.useGpu, cfg.venus, cfg.arm64GPU = true, true, true
		cfg.renderMode = "gpu"
	}
	if *audio {
		cfg.audio = "sdl"
	}
	if *exchange {
		cfg.share = filepath.Join(*dir, "exchange")
		if _, err := armDevelopmentPath(cfg.share); err != nil {
			return err
		}
		if err := os.MkdirAll(cfg.share, 0700); err != nil {
			return err
		}
		cfg.supportsSharing = true
	}
	var err error
	logFile, err = os.OpenFile(filepath.Join(cfg.vmDir, "shell.log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	defer func() { logFile.Close(); logFile = nil }()
	logf("ARM64 development start: guest=%s runtime=%s", pins.GuestManifest, pins.RuntimeArchive)
	data, err := os.ReadFile(filepath.Join(cfg.guestDir, "build-spec.json"))
	if err != nil {
		return err
	}
	var spec buildSpec
	if err := json.Unmarshal(data, &spec); err != nil {
		return err
	}
	cmdline := strings.ReplaceAll(spec.Runtime.KernelCommandLine, "console=tty0 ", "")
	cmdline = strings.ReplaceAll(cmdline, "console=hvc0", "console=ttyAMA0")
	cmdline = strings.ReplaceAll(cmdline, "mitigations=off", "")
	// ARM virt has no ICH9 sleep switches. Mask guest sleep targets for this
	// development route until suspend/resume has passed physical acceptance.
	cmdline += " systemd.mask=sleep.target systemd.mask=suspend.target systemd.mask=hibernate.target systemd.mask=hybrid-sleep.target"
	if cfg.instant {
		cmdline += " tryomarchy.instant=1"
	}
	if _, err := buildQemuArgsForArch(cfg, cmdline, "aarch64"); err != nil {
		return err
	}
	getUI().setStatus("ARM64 development: starting Omarchy")
	os.Setenv("SDL_GRAB_KEYBOARD", "0")
	go runGuestAgent(cfg.dir)
	go watchKeyboardPreferences(cfg.dir)
	go runWinKeyHook()
	go runWinKeyQmp()
	go runTitleEnforcer(cfg.dir, cfg.fullscreen, cfg.fullscreenDisplay)
	go runCursorReleaseGuard()
	go runCloseGuard()
	runClipboardBridge()
	runCameraBridge(cfg.desktop)
	runHelloBridge()
	cfg.followHostTimeZone = guestAcceptsTimeZone(spec)
	if cfg.followHostTimeZone {
		stopTimeZone := startTimeZoneBridge(func() string {
			return ianaZoneForWindows(hostTimeZoneKey())
		})
		defer stopTimeZone()
	}
	if cfg.audio == "sdl" && audioRuntimeSupportsLiveRouting(cfg.qemu) {
		runAudioBridge(cfg.dir, cfg.qemu, cfg.desktop.MicrophoneDisabled)
	}
	if *shutdownAfter > 0 {
		go func() {
			deadline := time.Now().Add(3 * time.Minute)
			for !bootAnnouncedReady.Load() && time.Now().Before(deadline) {
				time.Sleep(200 * time.Millisecond)
			}
			if !bootAnnouncedReady.Load() {
				logf("ARM test did not observe readiness")
				return
			}
			time.Sleep(*shutdownAfter)
			if qmp := qmpConnect(qmpToolsPort, 5*time.Second); qmp != nil {
				defer qmp.close()
				logf("ARM development test: requesting guest poweroff")
				_ = qmp.writeLine(`{"execute":"system_powerdown"}`)
			}
		}()
	}
	for supervise(cfg, cmdline) {
		logf("ARM64 development guest reboot")
	}
	logf("ARM64 development stopped; clean=%v", guestExitedCleanly.Load())
	return nil
}
