# Windows ARM64 WHPX direct-boot proof — 2026-10-28

A native ARM64 QEMU booted a disposable AArch64 Alpine Linux guest to its
serial login prompt using WHPX on physical Windows ARM64 hardware. This is an
accelerator and direct kernel/initramfs boot check, not a Try Omarchy guest or
runtime acceptance test.

## Host and test artifacts

- CPU: Snapdragon X2 Elite Extreme X2E96100, Qualcomm Oryon CPU.
- OS: Microsoft Windows 11 Pro, ARM64, 26H1, build 28000.3231.
- GPU: Qualcomm Adreno X2-90, driver 32.0.149.0 (not exercised by this test).
- Test QEMU: MSYS2 CLANGARM64 package, QEMU 11.1.2; executable PE machine
  `0xAA64` (ARM64); `qemu-system-aarch64.exe` SHA-256
  `0479d85fbb1e730ebf491e373bd43bfaac9efb97817e0f213078f1c9e9720ba3`.
  This is stock QEMU, not the project's patched WINQ-EMU runtime.
- Test media: [Alpine Linux 3.21.9 aarch64 virt ISO](https://dl-cdn.alpinelinux.org/alpine/v3.21/releases/aarch64/alpine-virt-3.21.9-aarch64.iso),
  SHA-256 `c98a22b9e60b772b766dfc2e3afdcccd25bd88be0888130b5e653df6be998f81`.
  Its hash matched the [published checksum](https://dl-cdn.alpinelinux.org/alpine/v3.21/releases/aarch64/alpine-virt-3.21.9-aarch64.iso.sha256).
  GPG verified the [detached signature](https://dl-cdn.alpinelinux.org/alpine/v3.21/releases/aarch64/alpine-virt-3.21.9-aarch64.iso.asc)
  using the [Alpine signing key](https://alpinelinux.org/keys/ncopa.asc);
  the fingerprint `0482 D840 22F5 2DF1 C4E7 CD43 293A CD09 07D9 495A`
  matched [Alpine's downloads page](https://alpinelinux.org/downloads/).
- Extracted from that verified ISO: `boot/vmlinuz-virt` SHA-256
  `85b50afdf48bd86745ea45cf6abe23571644a92c7cb8be2598b565b10dafbb76`;
  `boot/initramfs-virt` SHA-256
  `8a9c2fc62e37ea74c66dad5c140fec7b2ea6dc0708170b958207c746d811fcc5`.

## Procedure and observations

With the QEMU binary directory on `PATH` and the verified ISO and extracted
`boot/` directory in the working directory, the accelerator query was:

```powershell
qemu-system-aarch64.exe -accel help
```

The binary listed `whpx` and `tcg`. The following direct-boot command selected
WHPX explicitly; no fallback accelerator was supplied. It attached the ISO
read-only and did not attach a writable disk or network:

```powershell
qemu-system-aarch64.exe -machine virt -accel whpx -cpu host -m 1024 -smp 2 `
  -display none -serial file:proof-serial.log -no-reboot -nic none `
  -kernel boot/vmlinuz-virt -initrd boot/initramfs-virt `
  -append "modules=loop,squashfs,sd-mod,usb-storage console=ttyAMA0" `
  -drive file=alpine-virt-3.21.9-aarch64.iso,if=none,id=cd,format=raw,media=cdrom,readonly=on `
  -device virtio-scsi-pci -device scsi-cd,drive=cd
```

Selected lines from the serial log:

```text
[    0.000000] Linux version 6.12.114-0-virt (buildozer@build-3-21-aarch64) (gcc (Alpine 14.2.0) 14.2.0, GNU ld (GNU Binutils) 2.43.1) #1-Alpine SMP PREEMPT_DYNAMIC 2026-10-21 12:19:03
[    0.009913] smp: Brought up 1 node, 2 CPUs
   OpenRC 0.55.1 is starting up Linux 6.12.114-0-virt (aarch64)
Kernel 6.12.114-0-virt on an aarch64 (/dev/ttyAMA0)
localhost login:
```

The disposable QEMU process was stopped after the login prompt. No guest
shutdown or persistence was tested. A first independent run also reached the
login prompt with serial output on standard output.

## Host Vulkan inventory

The native ARM64 `C:\Windows\System32\vulkaninfo.exe --summary` exited
successfully and enumerated the Qualcomm Adreno X2-90 with the Qualcomm Adreno
Vulkan driver and Vulkan API 1.4.295. It also listed Mesa Dozen devices for
the Adreno and Microsoft Basic Render Driver. The loader emitted warnings
about layer/ICD manifests and surface capability emulation. This is a host
inventory only; neither VirGL nor Venus was exercised in the guest.

## Limits

This test establishes that the host, this native QEMU binary and this Linux
kernel can boot together with WHPX. It does not validate the patched project
runtime, an Omarchy image, graphics acceleration, desktop usability, disk
persistence, networking, host integration, updates, shutdown, or performance.
Do not use this result to enable ARM64 support or change a release pin.

## Patched QEMU engineering build

A second test on the same host booted the same verified Alpine ISO, kernel and
initramfs to `localhost login:` using an **unpackaged engineering build** of the
project's patched QEMU. The command above was unchanged except for the QEMU
executable, its DLL search path, and the serial output filename. `-accel help`
listed `whpx` and `tcg`; the boot command explicitly selected `-accel whpx`
without a fallback. The serial output included:

```text
[    0.000000] Linux version 6.12.114-0-virt (buildozer@build-3-21-aarch64) (gcc (Alpine 14.2.0) 14.2.0, GNU ld (GNU Binutils) 2.43.1) #1-Alpine SMP PREEMPT_DYNAMIC 2026-10-21 12:19:03
[    0.001224] smp: Brought up 1 node, 2 CPUs
   OpenRC 0.55.1 is starting up Linux 6.12.114-0-virt (aarch64)
Kernel 6.12.114-0-virt on an aarch64 (/dev/ttyAMA0)
localhost login:
```

QEMU stderr was empty. The disposable VM was stopped after 20 seconds; guest
shutdown was not tested. The QEMU executable reported version 11.0.0, had PE
machine `0xAA64`, and SHA-256
`af841973b6c7fe472269eeaeb5a7baaa5923d945a3651b9af2650574e8c91bda`.
The build's `libvirglrenderer-1.dll` on the DLL search path had SHA-256
`34d2d7e2933e8cf136f1ef0bc7eb9b89e68c643928fffa7f087c4e11b1234bad`;
this headless boot did not exercise the renderer.

The engineering build used the QEMU and virglrenderer source revisions in
`runtime-build/sources.lock.json` (`2ce303cfbbc8b0e4a7a3c66e27a094a980426d73`
and `e80354b8f5a0dedc62374b905a181874682659cc` respectively), with the 24
QEMU and five renderer patches locked at the start of the experiment hash-checked
and applied. Two
additional **proof-only source changes** were made outside the repository:

- In `accel/whpx/whpx-common.c`, guard both the `host-cpu.h` include and
  `acc->cpu_target_realize = host_cpu_realizefn` with `#ifdef TARGET_I386`.
- In renderer `src/mesa/compat/c11/threads_win32.h`, declare
  `impl_tss_dtor_invoke(void)` instead of `impl_tss_dtor_invoke()`.

The build used MSYS2 CLANGARM64, Clang 23.1.4 and Meson 1.12.1, with
`--target-list=aarch64-softmmu --enable-whpx --enable-opengl
--enable-virglrenderer --enable-slirp --enable-libusb --disable-docs
--disable-plugins --disable-guest-agent` and Meson `werror=false`. Its DLL
search path put the proof-built renderer directory ahead of the MSYS2
CLANGARM64 binary directory. The additional source changes were not part of
the locked patch series used for this run; they were subsequently added as
QEMU patch 0025 and renderer patch 0006. The MSYS2 package set was not
locked, warnings were not treated as errors, and the runtime was not packaged
or checked as a complete PE/DLL dependency chain. This is feasibility evidence,
not a reproducible or release-ready runtime, and it does not change the limits
above.

## Clean ARM runtime recipe and extracted boot

The corrected ARM64 runtime recipe later completed from a fresh source checkout.
It verified the runtime and corresponding-source archives, PE machine types,
manifest, source and patch hashes, and extracted a fresh smoke directory. The
runtime archive SHA-256 was
`9a5f5e0abf10552cab3d203043f4ee6100653be00f430cfb5e6a21da37c169e0`;
the corresponding-source archive SHA-256 was
`81280435976c53f3ffb03b271441eab5e8b5cd92114ea3a62871d40f693f5451`.

With PATH restricted to Windows system directories, the freshly extracted
QEMU executable (SHA-256
`f2f651c733754fec40ceca0df5652c33655df8577d08ed7ef6f46c483960538c`)
booted the verified Alpine guest above with WHPX to its serial login. Its
stderr was empty, and the disposable VM was stopped. This checks the headless
boot dependency path only. Dependency versions are recorded but not fully
pinned, and two builds differed in their archive hashes. The runtime remains
an engineering candidate; the Venus workload failure below remains open.

## Experimental Windows-integrated ARM guest

An **unpublished, resumed engineering build** of the Windows guest was booted
headlessly on the same physical host. The locked Windows guest source and its
151 patches were applied before an ARM-only scratch adaptation. The build
resolved 677 packages from the ARM repositories, installed them with package
signatures required, verified the pinned Omarchy source, applied the Windows
backports, built the patched Aquamarine package and the battery DKMS module,
and generated the final initramfs including the `tryomarchy_compat` hook.
The builder stopped at its x86-specific Aquamarine minimum-version validator;
a scratch-only validation change allowed the existing staged root to finish.
This was not a clean end-to-end build of the committed patch series.

The generated kernel, initramfs and compressed and raw disk hashes matched the
build's manifest. Selected SHA-256 hashes:

| Artifact | SHA-256 |
| --- | --- |
| `vmlinuz-linux` (ARM `/boot/Image`) | `e673566ad0cb249209996ab5f30a5e6bbd1ffd30ff9978ffceaa319e13967a34` |
| `initramfs-linux.img` | `d38a124c63cea1a4e4d427494e11a89435ed5d70db782796a845ebea7f6e660e` |
| `rootfs.ext4` | `2181cd8415b3f975c52b4eadcb0fbeecfdfebfca08530341d32681c61ae9d216` |
| `rootfs.ext4.zst` | `29be3a3a7feff573ac12cd498dec05140723bfe0263fed28c3762f117ca178e8` |

The ext4 image passed all five `e2fsck` passes. A new QCOW2 overlay backed by
that image kept the factory disk untouched. With a loopback listener for the
Windows launcher's readiness port, the proof QEMU 11.0.0 executable and its
collected DLLs were used with this command (the working directory held the
four named guest files):

```powershell
qemu-system-aarch64.exe -machine virt,accel=whpx -cpu host -m 4096 -smp 4 `
  -display none -device virtio-gpu-pci -serial file:omarchy-serial.log `
  -no-reboot -drive file=disposable.qcow2,format=qcow2,if=virtio `
  -kernel vmlinuz-linux -initrd initramfs-linux.img `
  -append "root=/dev/vda rw rootwait console=ttyAMA0 loglevel=4 systemd.show_status=true omarchy.qemu=1 tryomarchy.render=cpu tryomarchy.instant=1" `
  -device virtio-keyboard-pci -device virtio-tablet-pci `
  -netdev user,id=n0 -device virtio-net-pci,netdev=n0,romfile= `
  -device virtio-rng-pci -audiodev none,id=snd `
  -device virtio-sound-pci,audiodev=snd
```

The serial log showed the clean `/dev/vda` filesystem check, root mount,
`tryomarchy_compat` hook, network-online target, serial getty and guest agent.
The loopback listener received `ready`, and QEMU was then stopped. QEMU stderr
contained two `virtio_input_hid_handle_status: unknown type 20` messages.

The readiness message confirms this guest reached the host's userspace
readiness protocol. It does not confirm completed owner provisioning, a
Hyprland desktop, graphics acceleration, input, audio, persistence, guest
shutdown, updates or feature parity. The next build must run the eventual
reviewed patch series cleanly and repeat these checks, followed by physical
interactive desktop acceptance. This experiment must not be used as a release
pin or as justification to lift the ARM64 launcher guard.

## Clean engineering guest build and readiness boot

A subsequent ARM64 guest build ran continuously from the beginning through
`Guest build complete` without resuming a staged root. It used the integrated
ARM guest spec and builder scripts, a native `linux/arm64` Docker container
based on the sibling Mac project's Alpine/Arch Linux ARM bootstrap, and the
previously downloaded package cache. The transaction was resolved against the
ARM package lock and package signatures were required. The builder imported
the fingerprint-checked Omarchy key into the new target keyring alongside the
Arch Linux ARM keyring. It built the Windows-pinned Omarchy source, the ARM
Aquamarine rebuild, mise, the battery DKMS module and the final compatibility
initramfs; `e2fsck` completed all five passes. The later output-directory
safety guards affect selection before building and were added after this run.
This was a direct invocation of the guest builder inside a prepared container,
not an end-to-end run of the release wrapper or its newly added Containerfile.
That Containerfile was separately built successfully on ARM64.

The clean artifacts were copied into a newly created test directory. Their
SHA-256 hashes matched this build's `SHA256SUMS` before boot:

| Artifact | SHA-256 |
| --- | --- |
| `build-spec.json` | `fef464d9529a869aeff3b05d9279572cb8c98037b2e301acdceb201daac88770` |
| `guest-manifest.json` | `37a3f7c065e3b56b6a46ba30c003c3c1e33cabd530cd36d3415ebec332601f9b` |
| `vmlinuz-linux` | `e673566ad0cb249209996ab5f30a5e6bbd1ffd30ff9978ffceaa319e13967a34` |
| `initramfs-linux.img` | `ce78918ca4734e27b4432cc9800c17154b10a33e9b225b9a89fe7393b7ca27f8` |
| `rootfs.ext4` | `2548e7c3b18a56b7abb2deee75bccd08ebdd99c4bf4db6087c3972310aab78b5` |
| `rootfs.ext4.zst` | `a25f105af6105a125757a2b439aee1b4b68c06665e58b00abdbeb273b7a172ae` |

The root filesystem and initramfs hashes differ from the earlier resumed
engineering build. The clean build's spec hash matches `spec-aarch64.json`
in the experimental builder patch. A fresh QCOW2 overlay was created over the
verified raw image and the same headless WHPX command above was run on the
same machine. Its loopback listener received `ready`; serial output showed the
root filesystem mounted, the `tryomarchy_compat` hook, network-online target,
serial login and guest agent. QEMU stderr again contained two
`virtio_input_hid_handle_status: unknown type 20` messages. The disposable VM
was stopped after readiness, and the raw factory disk's SHA-256 was checked
again and remained unchanged.

The readiness signal precedes verification of the interactive owner setup or
Hyprland desktop. This run does not establish GPU acceleration, working input
or audio, persistence, updates, clean shutdown, or feature parity. A signed
production payload and architecture-specific release routing are still absent;
the ARM64 launcher guard remains in place.

## CPU desktop and virtual keyboard observations

The clean-build guest was started again on the same Snapdragon host with a
new QCOW2 overlay and the headless WHPX command above. QEMU had `-display
none`, `virtio-gpu-pci`, and the guest command line selected
`tryomarchy.render=cpu`; QMP was bound to loopback. The Windows readiness
listener received `ready`. QMP framebuffer captures at approximately 25 and
110 seconds after QMP initialization both showed the Omarchy desktop, including
its wallpaper, top bar and welcome notifications. The visible clock advanced
and QMP remained responsive. This is an observed desktop framebuffer; the
renderer was not independently identified with `glxinfo`.

A separate run used another new overlay. At approximately 35 seconds after
QMP initialization, its framebuffer showed the desktop without the menu.
The following QMP command returned success:

```json
{"execute":"send-key","arguments":{"keys":[{"type":"qcode","data":"meta_l"},{"type":"qcode","data":"spc"}],"hold-time":150}}
```

A framebuffer capture five seconds later visibly showed the Omarchy menu.
This exercises the QEMU virtual keyboard and guest shortcut. It does not test
Windows physical-key forwarding or touchpad/mouse behavior.

The PNGs converted from the QMP PPM captures were retained in the local proof
workspace outside the repository:

| Capture | SHA-256 |
| --- | --- |
| `desktop-25.png` | `ebf9153c416e645b7497892fe04b44263efb6402d16f1c5c3ef2a7c4491f0c36` |
| `desktop-110.png` | `edd8611ac7744a0c1f8a2b48a765821f5fab218c294b3eb9cbcd7550395d23e3` |
| `keyboard-before.png` | `19cfb9cb08a4a569e40da8d217e2cf0aea5ed500591147c2d97a3a01e1a97c6d` |
| `keyboard-after.png` | `b7f86995aae5f63a92cc63d296cbe4500a28b22745dfde0f299c42f94666806f` |

Both disposable QEMU processes exited after a QMP `quit`; this did not test
clean guest shutdown. Each reported two `virtio_input_hid_handle_status:
unknown type 20` messages on stderr. The overlays remain available for
inspection. The results do not establish hardware-accelerated graphics, audio,
persistence, update safety, Windows launcher integrations or feature parity.

## Experimental ARM64 GPU and Venus probes

The clean engineering guest was tested on the same Snapdragon X2 Elite Extreme
and Adreno X2-90 host. The candidate runtime archive and extracted executable
were engineering artifacts, not a signed public release:

| Artifact | SHA-256 |
| --- | --- |
| `winq-emu-alpha10-portable-arm64.zip` | `987b354ac6ea4d5fdf7d2d3cdad97e077568e83a9dc538621672d0fe2ba2d558` |
| `qemu-system-aarch64.exe` | `42e162902c2381c1f6b6c21dd88eacb4ff22fde81ffb78aff793dc41cd74955f` |
| `libvirglrenderer-1.dll` | `66589ce3bffe6e296e6b6bd69d8ac7327724c247ef4f10801ad4fac2605f65bb` |
| `vulkan-1.dll` | `36f0288dce9ca0b692fa0da91cbd18ef45c39ca84782bd44916f48e3b4d4e891` |

Each VM used WHPX, four vCPUs, 4 GiB guest RAM, `virt`, `-cpu host`, the
clean guest's verified kernel/initramfs, and a disposable QCOW2 overlay. The
working directory held the clean guest artifacts and an isolated `gpu-share`
folder used only for the diagnostic scripts and reports. The QEMU executable
and its DLLs were loaded from the extracted runtime; `PATH` contained only
Windows system directories. The relevant arguments were:

```text
-machine virt,accel=whpx -cpu host -m 4096 -smp 4
-display sdl,gl=on,show-cursor=off
-device virtio-gpu-gl-pci,blob=on,hostmem=2G,venus=on
-drive file=<disposable-overlay>,format=qcow2,if=virtio
-kernel vmlinuz-linux -initrd initramfs-linux.img
-append "root=/dev/vda rw rootwait console=ttyAMA0 loglevel=4 systemd.show_status=true omarchy.qemu=1 tryomarchy.render=gpu tryomarchy.instant=1"
-device virtio-keyboard-pci -device virtio-tablet-pci
-netdev user,id=n0 -device virtio-net-pci,netdev=n0,romfile=
-device virtio-rng-pci -audiodev none,id=snd
-device virtio-sound-pci,audiodev=snd
-virtfs local,path=gpu-share,mount_tag=hostshare,security_model=none
```

The run also used loopback QMP and readiness listeners, a serial log and
`-no-reboot`. In the first overlay, `mesa-utils` 9.0.0-7 and `vulkan-tools`
1.4.363.0-1 were installed from the guest's signature-required repositories;
the verified factory image was not modified. The guest started its desktop,
and `glxinfo -B` reported `Accelerated: yes` and renderer
`virgl (D3D12 (Qualcomm(R) Adreno(TM) X2-90 GPU))`, Mesa 26.2.5. This is
renderer identity evidence for accelerated OpenGL, not a performance or
application-compatibility benchmark.

With `hostmem=2G`, default `vulkaninfo --summary` listed only CPU llvmpipe.
The guest had the `vulkan-virtio` package and `virtio_icd.json`, and the
session had no `VK_DRIVER_FILES` override. Forcing that ICD failed with
`ERROR_INITIALIZATION_FAILED`. The guest kernel reported `bar shorter than
cap offset+len`, `+resource_blob -host_visible` and three capsets. QEMU's ARM
`virt` defaults include a 512 GiB high PCI MMIO aperture, but this observation
alone does not establish why the 2 GiB BAR was unavailable on this host.

A second run used a child overlay and changed only the device option to
`hostmem=256M`. The kernel reported `Host memory window: 0x10000000
+0x10000000` and `+resource_blob +host_visible`; the PCI resource listing
showed BAR 4 at `0x10000000`–`0x1fffffff`. VirGL OpenGL still identified the
Qualcomm GPU. Both default Vulkan enumeration and an explicitly forced
`virtio_icd.json` listed `Virtio-GPU Venus (Qualcomm(R) Adreno(TM) X2-90 GPU)`
as an integrated GPU with `DRIVER_ID_MESA_VENUS`; the forced query exited 0.
Another boot of a child overlay also enumerated that Venus device. Enumeration
alone does not establish working rendering or which device applications use.

A bounded workload was then attempted on a further child overlay with the
same 256 MiB device settings:

```sh
VK_DRIVER_FILES=/usr/share/vulkan/icd.d/virtio_icd.json timeout 30s \
  vkcube --wsi wayland --gpu_number 0 --c 600 --width 400 --height 400 --suppress_popups
```

The host saw the probe reach the workload section after enumerating the
Qualcomm Venus device, but no completion marker or `grim` screenshot arrived
within 100 seconds after the command was submitted. The matching QEMU process
was then stopped externally. The workload's stdout and stderr were directed to
the disposable guest's `/tmp` and were not recovered after the stop, so its
exit status, whether it rendered frames, and whether the VM, compositor, GPU
path or host-share reporting stalled are unknown. This is a noncompletion,
not a successful Vulkan rendering test.

A separate paused `egl-headless` initialization attempt exited with Windows
access violation `0xC0000005` and no stderr; the SDL GL configuration stayed
alive and booted the guest. QMP `screendump` on the SDL GL path returned `no
surface`, so no GPU framebuffer screenshot is claimed. All disposable QEMU
processes have been stopped; the overlays and full diagnostic logs remain in
the local proof workspace outside the repository. Selected full-report hashes:

| Local report | SHA-256 |
| --- | --- |
| `gpu-report.txt` (2 GiB default) | `f4d96b6873fbd4072085075112a09a9b85722f418706c807d9ce96b6f4203e8e` |
| `venus-report.txt` (2 GiB forced ICD) | `e56cbefab1a03670c68b50d2468b816fef7119ca2be325cfc7a05e80457e18e8` |
| `small-report.txt` (256 MiB) | `60aadb7a39cfbbe93b557ed961b022e67921ec969cc6ac93070520cfeadce9f8` |
| `cube-report.txt` (incomplete workload) | `ab544843914a7fe04ec7583a8f3f34860d4718725beddc412783c90d0eabefac` |

These results do not establish production-ready Vulkan, GPU performance,
physical input, audio, persistence, update safety or overall feature parity.
The 256 MiB setting is a feasibility observation, not a validated production
resource policy.

### Controlled Venus stall observation

A further run used a new child overlay over the 256 MiB test overlay, with the
same WHPX/SDL/`hostmem=256M` options and the same bounded `vkcube` command.
The guest wrote `vkcube` stdout and stderr directly to the isolated 9p host
share; a separate guest process wrote numbered heartbeats to the serial
console once per second. The host queried QMP status after the keypress that
started the probe. The guest reached its normal `ready` signal first.

`vkcube` stderr recorded selection of `GPU 0: Virtio-GPU Venus (Qualcomm(R)
Adreno(TM) X2-90 GPU), type: IntegratedGpu`. The serial heartbeat reached
`GPU_HEARTBEAT_4` around workload launch and did not advance afterward. The
host's QMP `query-status` request, issued five seconds after launch, timed out;
QMP `quit` then failed on the timed-out connection. The host watchdog terminated
the disposable QEMU process. No workload completion marker, guest exit status,
or frame capture was obtained. This provides evidence of a broader control or
guest stall alongside the workload, but does not establish which thread or
component caused it. The guest `timeout` could not be observed completing, and
termination was not a clean guest shutdown. No test QEMU process remained.

The full local logs remain outside the repository:

| Local log | SHA-256 |
| --- | --- |
| `health-host.log` | `03adb723981d97cb0b74550afa074981e64eb0e97189be9074971f8c8c7b1e2c` |
| `health-serial.log` | `3e6c5b9b6f077ac503a71fadc42a32a6890fb338a0a89b80d2328073d75b971d` |
| `health-stderr.log` | `000559953a56c60406baa8080e124e085c7cba2eba90ff293e2b5020cdbb47d7` |
| `health-report.txt` | `59df12af2ed357ee564d006edb7bcb91dc156ad7caf697e73453d1597857be61` |
| `health-vkcube-stdout.txt` (empty) | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `health-vkcube-stderr.txt` | `73c7e93974fef830cb92c40ea90bd16936821d77643491fcbeb8950666cabd97` |

### Diagnostic Venus renderer trace

On 2026-10-29 UTC, a repeat of the controlled 256 MiB run used a separate
copy of the candidate runtime, replacing only its renderer DLL with an
instrumented build. The new throwaway `gpu-trace.qcow2` overlay was based on
the earlier disposable 256 MiB overlay, including the signature-verified guest
`mesa-utils` and `vulkan-tools` packages; the factory image and original
runtime were not modified. The QEMU executable SHA-256 was
`42e162902c2381c1f6b6c21dd88eacb4ff22fde81ffb78aff793dc41cd74955f`, the
instrumented renderer was
`5ea681956da29118b2f9b934d1b08101686a4e70fcac80c476c409cbd9b20f92`,
and the Vulkan loader was
`36f0288dce9ca0b692fa0da91cbd18ef45c39ca84782bd44916f48e3b4d4e891`.
The renderer uses the locked renderer source and project patches 0001–0006,
plus diagnostic-only edits to proxy context, renderer and server sources to
restore Venus logging and print synchronization settings. Instrumentation may
change timing; this was not a release renderer.

The host used system-only `PATH`, `OMARCHY_ARM_TRACE=1` and
`VIRGL_LOG_LEVEL=debug`. QEMU used `virt,accel=whpx`, `-cpu host`, 4 GiB,
four CPUs, `-display sdl,gl=on,show-cursor=off`, and
`virtio-gpu-gl-pci,blob=on,hostmem=256M,venus=on`; the guest received the
same kernel and command line described above and the same forced-ICD bounded
`vkcube` invocation as the controlled test. Full reproducible arguments,
QMP instrumentation, and guest command are in the local `trace-proof.py` and
`gpu-share/trace-check.sh` artifacts.

The guest again sent `ready`, selected the Qualcomm Venus device and emitted
four serial heartbeats. QMP `query-status` timed out after the probe was
started, `quit` failed, and the watchdog terminated QEMU; no frame or
workload completion was observed, and no QEMU process remained. The trace
reported `proxy flags=0xac0 thread_sync=0 async=0`, `context fence init
thread_sync=0 async=0`, and `venus: vkr: mem is not exportable`. This identifies
an observed renderer condition, not its causal relationship to the stall.

| Local proof artifact | SHA-256 |
| --- | --- |
| `trace-proof.py` | `860151a2f7c67b58560435324c52d3d566ca80b7f0e33e773fe0005c649d5bb5` |
| `gpu-share/trace-check.sh` | `2f28d7d2cdc0c41694e479a0eba44e87f8874637b8fdd7501ca9906f1a011999` |
| `trace-host.log` | `03adb723981d97cb0b74550afa074981e64eb0e97189be9074971f8c8c7b1e2c` |
| `trace-stderr.log` | `53676de39ced5754eb347713fc86535794692ae8356a089f165bbae22545121f` |
| `trace-serial.log` | `6a6196aafaa2a13581b9add1f4f2e89fb69fc62b5a35886c9c0cc893e3b2eed0` |
| `gpu-share/trace-report.txt` | `59df12af2ed357ee564d006edb7bcb91dc156ad7caf697e73453d1597857be61` |
| `gpu-share/trace-vkcube-stdout.txt` (empty) | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `gpu-share/trace-vkcube-stderr.txt` | `73c7e93974fef830cb92c40ea90bd16936821d77643491fcbeb8950666cabd97` |
| `gpu-trace.qcow2` after termination | `649028353a1e364bc5c49aa39feb7a352dd229c2ed393a3c2c2d824d8cb539f3` |


## Native launcher and protocol follow-up (2026-10-29 UTC)

The `arm64dev` build tag now provides an explicit `-arm64-dev` entry point.
See `docs/WINDOWS-ARM64-DEVELOPMENT.md` for the isolated installation contract.
The default release guard and public artifact pins remain unchanged.

The native app installed the reviewed clean ARM guest and candidate3 runtime
into `C:/temp/omarchy-arm64-launcher-test`, using independently supplied local
hash pins. First launch reached userspace readiness about ten seconds after
QEMU startup, connected the guest agent and clipboard bridge, and completed a
QMP-requested guest poweroff with launcher exit 0 and `clean=true`. A second
corrected audio-enabled run reached readiness in five seconds, connected the
volume-sync bridge, rendered a captured desktop, stayed up for 90 seconds,
and powered off cleanly. The native launcher screenshot is
`C:/temp/omarchy-arm64-launcher-test/vm/launcher-desktop.png`.

Physical testing found and corrected two issues in the new entry point:

- Disabling capture with `in.voices=0` still left virtio-snd advertising a
  recording stream. It failed to create that backend. ARM capture-disabled
  arguments now use `streams=1` while retaining `in.voices=0`.
- The entry point initially omitted the existing audio bridge initialization.
  QEMU's asynchronous failed-connect path aborted in
  `yank_unregister_function` when the audio control endpoint was absent.
  A native debug-event runner and ARM frame-pointer stack established that
  call path. Starting the existing bridge, as ordinary `main` does, resolved
  this launcher failure. The debugger's protected-socket-handle first-chance
  exception was separate; no speculative socket-close patch was adopted.

A debug run also observed foreign EGL/GLES DLLs from another application on
PATH. ARM development now runs QEMU from its verified binary directory with
Windows-only PATH and SDL software display selection for CPU mode. This is
covered by a focused command-environment test.

The native guest acceptance script exercised the actual launcher with
`-instant -audio -exchange -shutdown-after 120s`. It observed:

- `uname -m` = `aarch64`; `/dev/vda` = 25769803776 bytes; ext4 root and 9p share.
- Matching SHA256 for a 64 KiB host-to-guest-to-host file.
- PipeWire playback sinks and monitor sources only; no recording source.
- `pw-play` returned 0 for a one-second quiet 440 Hz fixture. This is an API
  playback result, not independent proof that a person heard the speakers.
- `America/New_York` timezone, all four sleep targets masked, HTTPS request
  to the Arch Linux ARM site successful, and a live Hyprland monitor.
- `SCRIPT_EXIT=0`, followed by a clean supervised guest poweroff.

The first Unicode filename probe was invalid: Windows PowerShell encoded
literal non-ASCII text incorrectly in the generated test script. Its stored
source already contained mojibake before reaching the guest. The corrected
probe uses ASCII Unicode escapes in the host generator; do not attribute
that first result to the 9p implementation. The corrected repeat passed:
`caf\u00e9-arm64-\u6587\u4ef6.bin` retained the expected 64 KiB SHA256
`7daca2095d0438260fa849183dfc67faa459fdf4936e1bc91eec6b281b27e4c2`,
rename succeeded, and a seeded home-directory file survived a supervised
restart (`PERSISTENCE_RELAUNCH_EXIT=0`).

Native `go test -tags arm64dev ./...` passed in 73.249 seconds. Targeted
installer/ARM topology tests, ARM vet with the project's established
`-unsafeptr=false` contract, and both default/tagged AMD64 cross-builds passed.
An earlier run with the entire MSYS2 bin directory on PATH selected its
optional x86 TCG save-session test runtime and hit three migration timeouts.
The normal native test environment passed; that optional TCG combination is
not evidence of ARM saved-session support.

### The Venus VM-wide freeze was a protocol framing bug

On Windows, the proxy client reads a fixed resource reply followed by an
explicit descriptor count. The worker's failed CREATE_RESOURCE branch sent
only the fixed reply. The client blocked waiting for the missing count while
QEMU held its main loop. Renderer patch
`0007-complete-windows-resource-error-replies.patch` sends a complete reply
with count zero on failure and removes the unused incomplete send helper.

`runtime-build/test-proxy-resource-reply.py` compiles the actual worker case
and Windows send/receive functions into a bounded byte-stream fixture. The
original source fails with `resource reply omitted its descriptor count`;
the patched source passes alternating rejected and successful requests.
The locked build runs this fixture and records the patch hash.

Physical forced-Venus tests with the corrected reply still failed their
application allocation, but guest serial heartbeats and QMP remained live;
QMP quit completed with QEMU exit 0. This establishes the freeze fix, not a
working Vulkan renderer. Local proof prefixes are `reply`, `dozen`, `alloc`,
`sw`, `sync`, and `req` under the clean guest proof directory.

### Dozen host imports and resource binding

A native Vulkan probe against the installed Dozen driver found:

| Query | Allowed memory type mask |
| --- | --- |
| Ordinary transfer-source buffer | `0x7` |
| HOST_ALLOCATION external buffer | `0x1` (device-local only) |
| Imported shared-section host pointer | `0x6` (host-visible types) |

The external buffer and imported pointer masks do not intersect. Qualcomm's
native ICD does not advertise either external-memory Win32 or external-memory
host support on this driver, so it cannot take this shared-memory renderer
path directly.

Mesa 26.2.5 source was obtained from its official archive for a local driver
experiment (archive SHA256
`794b3d1729075dae7ebd47c7283b7ca0cdb5dec668f7f11cc0a5d82f6138a0a5`).
The native build recipe now pins this archive and the DirectX-Headers commit
in `runtime-build/mesa-arm64.lock.json`. A correction excludes HOST_ALLOCATION imports from
Dozen's shared-heap memory-type restriction in buffer and image requirements.
The rebuilt native driver reports mask `0x7` for the external-host buffer,
while the pointer mask remains `0x6`. No system ICD registration or graphics
driver installation was changed; `VK_DRIVER_FILES` selects a private JSON.

With that private driver, the Venus guest allocated and mapped host-visible
staging and uniform buffers. A native buffer-copy control then isolated a
second Dozen defect: `dzn_BindBufferMemory2` added imported-memory resource
flags to a local descriptor but passed the original descriptor to
`CreatePlacedResource`. Passing the corrected descriptor made native imported
buffer binding, GPU copies and fence completion succeed. The two Dozen
corrections are one locked Mesa patch.

The earlier queue-fence hypothesis was rejected. The device does not expose
Win32 fence export, and the observed fence failures followed device removal
caused by the invalid resource binding. No internal-fence workaround is part
of the recipe.

Renderer patch `0008-preserve-host-pointer-resource-classes.patch` preserves
ordinary buffer allocation on the host-pointer path and avoids coercing
HOST_ALLOCATION images to the legacy opaque-Win32 layout. Its native fixture
extracts and tests the actual buffer/image shim functions. The unpatched
buffer shim fails that fixture; the patched host and legacy cases pass.

An earlier experiment that relabeled device-local memory as host-visible was
rejected: it did not solve the import contract and was followed by an abnormal
QEMU exit during cleanup. It remains outside the repository. The Dozen
correction preserves the original memory properties instead.

### Visible Vulkan rendering and longer clean-source run

Direct Vulkan-to-GL dma-buf presentation produced a black desktop. Selecting
the existing shared-memory presentation path with `WINQ_DMABUF_SHIM_OFF=1`
rendered a textured LunarG cube and preserved the desktop. An initial run
completed 600 frames with application and QEMU exit 0.

A repeat used a clean production renderer build, the clean source-built
Mesa recipe, and QEMU from the freshly verified candidate4 archive. It forced
the guest virtio Vulkan ICD and device 0, Dozen on the Adreno X2-90. The cube
completed 6000 frames in 63 seconds with `vkcube_exit=0`; serial heartbeats
and QMP stayed responsive, post-workload QMP reported running, and QMP quit
gave QEMU exit 0. The captured `gpu-share/clean-cube-30.png` visibly contains
the textured cube and desktop. `glxinfo -B` separately reports accelerated
VirGL, D3D12, Adreno X2-90, OpenGL 4.2 and GLES 3.1. Local artifacts are under
the existing clean guest proof directory (`clean-proof.py`, `clean-serial.log`,
`clean-stderr.log`, and `gpu-share/clean-report.txt`).

Dozen prints a nonconformant-implementation warning. These results do not
establish Vulkan conformance, readback correctness across all workloads,
long-term stability or product feature parity. The complete candidate5
runtime is rebuilding with the Mesa driver, source/license inventory and
both renderer fixes; its packaged launcher acceptance is still pending.

Real input/clipboard roundtrips, peripherals, recovery, broader graphics
acceptance and full feature parity remain gates. No PR has been opened and
no changes have been pushed.

### Private dependency and native window checks (2026-10-29)

The full native tagged suite passed again in 74.886 seconds, followed by ARM
vet and default/tagged AMD64 cross-builds. Targeted installer/graphics profile
checks also pass after the environment and validator gates were added. The
release guest-wrapper tests passed all eight cases under WSL Python. Invoking
that POSIX harness with Windows Python and the WSL `bash.exe` first failed on
Windows path syntax; that invocation does not execute the wrapper correctly.
The PE and ARM DLL collector tests passed under native Windows Python.

The native host-import probe transfers a nonuniform 262144-byte pattern from
a Windows shared section through an optimal GPU image into a readback buffer.
It reported `HOST_IMPORT_IMAGE_READBACK_OK` on the Adreno X2-90. The first
standalone instance failed with a Windows-only PATH; a normal-PATH control
revealed that it found Obsidian's `DXIL.dll`. That control is not accepted as
portable packaging evidence.

The official Microsoft DXC 1.9.2609 Windows archive was obtained from its
GitHub release. Its SHA256 matches the release API digest
`ad31b1fc8443175d204f77a611fdb3ef2ec42759bdc2f1167368de24a4a7e7f1`.
The ARM64 DXIL DLL hash is
`d7f9893a7031b7967e136992ac751b07ef3baf9691f9a8b619bd9a6c0a7cfa15`;
Windows verified its Microsoft Corporation signature. Its only static imports
are Windows system libraries, and it has no delay imports. With this private
DLL, Windows-only PATH and implicit Vulkan layers disabled, the readback probe
passed with host-buffer mask `0x7`, pointer mask `0x6` and exit 0. The helper
and lock retain all three official license notices. This is a prebuilt binary
dependency with separate Microsoft terms; public distribution remains a review
item. No global ICD or system graphics driver was changed.

A repeat native CPU launcher run rendered the restored window. Native mouse
input opened the guest menu and launched Chromium to its initial terms screen;
that screen was dismissed. Alt+F4 opened the launcher's shutdown confirmation,
establishing the native keyboard-hook path. The UI helper could capture the
cross-process owned dialog but did not enumerate it as a separate target, so
its attempted confirmation click was rejected as targeting the wrong process.
No confirmation-click or close-button mouse-hook success is claimed. Private
QMP poweroff ended the run with launcher exit 0 and `clean=true`.

The development route now explicitly disables camera as well as microphone
capture. Its GPU environment strips inherited Vulkan variables and selects the
private ICD with implicit host layers disabled. The loader behavior follows
Khronos' documented `VK_LOADER_LAYERS_DISABLE=~implicit~` mechanism. Actual
clipboard roundtrips, complete resize/DPI behavior, Win-key physical input and
peripheral acceptance remain pending.

## Packaged launcher acceptance (2026-10-29)

The complete candidate5 source rebuild passed runtime/source archive verification:

| Archive | SHA256 |
| --- | --- |
| ARM64 runtime | `72fc42062a48c7796510459df389aa0a0d0e53857b3ee3fb9cc06215506913f2` |
| Corresponding source | `57bc97a7765d472e52b7babc93638f2873c7b8d2bb6b3a0b3c6ba0156e6c85ea` |

Candidate6 repackages those unchanged QEMU, renderer and Mesa binaries with the
independently pinned Microsoft DXIL validator, its notices and the updated
packaging recipe. `provenance/packaging-base.json` records that relationship.
It is not claimed to be a second full source rebuild. The updated verifier
checks its complete inventory, ARM64 PE types, Mesa/DXC locks and patch hashes,
licenses, corresponding source and both archive hashes:

| Archive | SHA256 |
| --- | --- |
| ARM64 runtime | `368a1fbfaad22fe032471a324c2010fa619ca5369e0d331c57344d214794676a` |
| Corresponding source | `aba8b1a86f6d81f53a1115d9b7470d55feab95d2cb7202c1e1e7c92e117b4470` |

The native development launcher installed candidate6 into the new isolated
`C:/temp/omarchy-arm64-launcher-gpu6` directory with the same independently
pinned clean guest. Initial userspace readiness took 39.4 seconds including
installation and verification. Readiness preceded the graphical session; the
input harness was corrected to wait for the session's clipboard connection.
The first workload attempt also identified missing test utilities in the
factory guest. The repeat installed signed `mesa-utils` 9.0.0-7,
`vulkan-tools` 1.4.363.0-1 and `vulkan-headers` 1:1.4.363.0-1 in the writable
overlay. GCC 16.1.1 was already present. The factory image was unchanged.

With 8 virtual CPUs and 8192 MiB RAM, the actual packaged launcher observed:

- Accelerated VirGL/OpenGL on D3D12 and the Qualcomm Adreno X2-90.
- The Linux variant of `test-vulkan-host-import.c` selected Venus on the
  Adreno, transferred a nonuniform pattern through an optimal GPU image and
  compared all 262144 readback bytes successfully.
- A normal cube completed 3000 frames in 44 seconds; the staging variant
  completed 3000 frames in 47 seconds. Both returned 0 and their captures
  visibly contain the textured cube. These are workload timings, not a
  controlled benchmark or Vulkan conformance result.
- The guest retained its existing `VN_PERF=no_async_present` profile. Neither
  workload added the earlier `no_async_mem_alloc` diagnostic override.
- QMP remained responsive during the workloads. The guest requested a reboot,
  the supervisor relaunched it, and a seeded home-directory file survived.
- Playback monitor sources only, no recording source; America/New_York timezone.
- Final QMP poweroff, launcher exit 0 and `clean=true`; total harness time
  156.9 seconds. Local reports are `exchange/gpu-acceptance-report2.txt` and
  `exchange/gpu-persistence-report.txt`; the host log is
  `C:/temp/omarchy-arm64-launcher-gpu6-proof2.log`.

| Guest capture | SHA256 |
| --- | --- |
| `exchange/cube-direct.png` | `88a25a581e207380bccc2738f6bc1bc052e57a9b41eee6c95d03651b860736d3` |
| `exchange/cube-staging.png` | `8ea61e94e057802c6ea789e4c3f3ae3d5e7854ccb466885d95fd171a7b6180fb` |

Omitting `-gpu` then exercised CPU fallback on that same disk and runtime.
It reported llvmpipe, preserved the GPU-session file, passed Unicode filename,
64 KiB file hashes, rename, HTTPS, timezone and playback API checks, and showed
no microphone source. The script returned 0 and the launcher powered off
cleanly. The host report writer initially failed to print Unicode under its
default code page; the UTF-8 repeat completed with launcher exit 0. The valid
repeat log is `C:/temp/omarchy-arm64-launcher-cpu6-proof2.log`.

A new regression test reproduced an installation-boundary bypass through a
Windows 8.3 parent alias in a disposable directory. The installer now resolves
the existing parent before overlap checks; the original code fails and the
corrected code passes. The full native tagged Go suite passed in 81.332 seconds
before this final boundary change; targeted installer/graphics checks, ARM vet
and both AMD64 cross-builds passed afterward. Fullscreen is exposed through
the existing shared controls; complete fullscreen/input acceptance is pending.

Native WHP reports a 39-bit physical address width. QEMU's ARM backend rounds
this down to a valid 36-bit PARange. Its default high PCI aperture is outside
that range; this is a source-based explanation to investigate for the larger
GPU BAR allocation failures, not a validated memory-map fix. Keep the tested
256 MiB aperture until a separate change passes native acceptance.

This is a working development checkpoint, not full product parity. Normal ARM
release controls remain disabled. Tray/settings/update/recovery management,
saved sessions, larger GPU apertures, physical input/audio/peripherals,
clipboard roundtrips, host power behavior and sustained application testing
remain gates before opening a PR or publishing an ARM release.
