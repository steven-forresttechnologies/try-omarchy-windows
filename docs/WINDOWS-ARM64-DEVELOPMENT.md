# Windows ARM64 development launcher

This is an engineering entry point for native Windows ARM64 and an aarch64
guest. It is compiled only with `-tags arm64dev` and requires `-arm64-dev` as
the first argument. The ordinary release launcher still rejects ARM64. No
public payload pin, updater, release artifact, or supported-platform claim is
changed by this entry point.

## Build and launch

Build in `app` with native ARM64 Go:

```powershell
go build -tags arm64dev -o TryOmarchy-arm64-dev.exe .
```

Build the guest with `scripts/release/build-guest.sh --architecture aarch64`
and the runtime in an MSYS2 CLANGARM64 shell with
`runtime-build/build-arm64.sh OUTPUT_DIRECTORY`. Review the build evidence and
obtain both hash pins independently before launching. The guest pin is the
SHA256 of `SHA256SUMS`; the runtime pin is the SHA256 of the complete portable
runtime ZIP. These are local development trust anchors, not public release
signatures.

```powershell
.\TryOmarchy-arm64-dev.exe -arm64-dev `
  -dir C:\OmarchyARM-Development `
  -guest C:\ReviewedARMGuest `
  -runtime C:\ReviewedARMRuntime\winq-emu-alpha10-portable-arm64.zip `
  -guest-sha256 <reviewed-SHA256SUMS-hash> `
  -runtime-sha256 <reviewed-runtime-ZIP-hash>
```

All three paths must be absolute. The destination must be a new directory
whose parent already exists. An existing directory is reusable only when its
ARM development identity, artifact hashes, runtime inventory, and disk backing
match the requested pins. Use another destination for a different candidate.

Optional flags:

| Flag | Behavior |
| --- | --- |
| `-instant` | Use the guest's quick-start account. |
| `-cpus 4` | Allocate 1–16 virtual CPUs. |
| `-memory 4096` | Allocate 2048–32768 MiB of guest RAM. |
| `-audio` | Enable SDL playback and the existing volume/device bridge; host microphone capture stays disabled. |
| `-exchange` | Expose only this installation's `exchange` folder at the normal guest host-share mount. |
| `-gpu` | Opt into the verified private Dozen ICD, VirGL and Venus with shared-memory presentation. Requires the reviewed graphics runtime profile. |
| `-fullscreen` | Start on the primary display using the existing fullscreen and cursor-release controls. |
| `-shutdown-after 90s` | Request guest poweroff this long after userspace readiness; intended for bounded acceptance runs. |

The timeout starts at the readiness service, which can precede the compositor.
It is not proof that a desktop or workload rendered successfully. Collect a
screenshot and workload results separately.

## Installation and launch boundaries

- Installation uses a private sibling staging directory and is published after
  verification. Interrupted staging is never adopted as an existing guest disk.
- Guest metadata must identify `image.architecture=aarch64` in `build-spec.json`
  and `guest.architecture=aarch64` in `guest-manifest.json`. The copied kernel,
  initramfs, raw factory image, and metadata must match the pinned sums.
- The runtime ZIP rejects traversal, duplicate names ignoring case, links,
  Windows reserved paths, and more than 2 GiB of extracted content. Every
  runtime file must match its manifest, and packaged executable images must
  be ARM64. The manifest remains bound to the independently pinned ZIP on
  every launch.
- An installation and its ancestry must contain no reparse points. The normal
  installation directory cannot overlap the development destination. Existing
  unmarked disks are refused. The writable 24 GiB qcow2 overlay always refers
  to its verified private factory image.
- QEMU runs from its verified binary directory with a Windows-only PATH. CPU
  mode uses SDL's software display backend so another application's EGL/GLES
  libraries cannot enter through a developer PATH or working directory.
  GPU mode drops inherited Vulkan selectors and disables implicit host Vulkan
  layers using the loader's documented `VK_LOADER_LAYERS_DISABLE=~implicit~`
  setting. Camera and microphone capture remain disabled in this entry point.
- QMP retains the launcher's private filesystem sockets. No privileged monitor
  is exposed over the guest-accessible user network. Existing single-instance
  and guest bridge peer checks are reused.
- ARM uses `virt,accel=whpx`, `-cpu host`, virtio devices, and the PL011 serial
  console. x86 CPU models, VGA, ICH9 sleep switches, and irqchip recovery are
  excluded. Guest sleep targets are masked pending host sleep/resume testing.
- GPU mode requires the source-built Mesa profile and both renderer resource
  fixes in the pinned runtime. Its ICD uses a private relative DLL path; no
  system driver registration changes. The ARM GPU has a tested 256 MiB host
  memory window. `WINQ_DMABUF_SHIM_OFF=1` selects shared-memory presentation
  because direct Vulkan-to-GL import produced a black desktop on this driver.
  Dozen reports that it is not a conformant Vulkan implementation. Successful
  workloads establish observed behavior, not conformance or full application
  compatibility. Omit `-gpu` for the CPU display path.
- Playback-only ARM guests advertise one sound stream when capture is disabled.

## Acceptance before a public ARM release or PR

The evidence log is
[`evidence/WINDOWS-ARM64-WHPX-BOOT-2026-10-28.md`](evidence/WINDOWS-ARM64-WHPX-BOOT-2026-10-28.md).
Passing an installer fixture or seeing a readiness message does not satisfy
these physical acceptance requirements.

| Area | Required evidence |
| --- | --- |
| Installation | Clean install, repeat launch, interrupted install, tampered artifacts, wrong architecture, reparse points, no adoption or reset of another disk. |
| Desktop | First-run setup and instant session, input, window resize, DPI, fullscreen, cursor, Win-key focus behavior, browser and terminal workloads. |
| Graphics | VirGL and Venus workload rendering, memory transfer/readback, synchronization, long run, failure recovery, and CPU fallback on this Adreno driver. |
| Audio | Actual playback, microphone-off privacy, routing and volume, device removal/reconnect, missing-device recovery. |
| Integration | Clipboard in both directions, Unicode file sharing and transfer, time/timezone, networking and forwarding, URL opening. |
| Lifecycle | Reboot, graceful close, failed boot, Windows session ending, host sleep/resume and low-memory behavior. |
| Recovery | ARM-aware backup/restore, snapshots, saved sessions, move, updates/rollback, recovery tools, and uninstall without crossing installation boundaries. |
| Peripherals | USB attachment/removal, camera and Windows Hello opt-in flows, touchpad and display behavior. |
| Packaging | Fresh runtime recipe, complete source/license inventory, independent pins, clean-machine DLL loading, existing x86 checks and native ARM checks. |

The development entry currently omits the ordinary tray, settings/update,
recovery, and installation-management flows because those paths still select
x86 artifacts or assume the release installation format. Feature parity remains
an acceptance gate. Do not enable those controls by removing the architecture
guard.

The current runtime explicitly blocks migration because its WHPX GIC state
save/restore path is not implemented. Inspect that boundary without a user disk:

```powershell
python runtime-build/smoke-arm64-migration.py C:\ReviewedRuntime\bin\qemu-system-aarch64.exe --output C:\Proof\migration.json
```

The probe starts a paused, diskless VM and discards any outgoing migration
stream. A successful probe process is a collected observation, not a saved-session
acceptance result. An incoming restore and real guest/device continuity must
still be tested before saved-session controls can be enabled.

## Native host-import readback

`runtime-build/test-vulkan-host-import.c` tests the specific imported-memory
contract behind the Venus failures. In CLANGARM64, compile it against the
Vulkan loader and headers, then run the resulting executable beside the
reviewed private runtime DLLs. Set `VK_DRIVER_FILES` to that runtime's
`dzn-arm64.json`, use a Windows-only PATH, disable implicit Vulkan layers,
and impose a process timeout (25 seconds was used for this machine).

Success prints the physical device, intersecting resource/pointer memory masks
and `HOST_IMPORT_IMAGE_READBACK_OK bytes=262144`. The probe imports a Windows
shared section, transfers a nonuniform byte pattern through an optimal GPU
image, waits for its fence and compares every readback byte. A CPU Vulkan
device cannot satisfy it. This complements the guest Venus rendering test;
it does not replace it.

Standalone Dozen also needs a DXIL validator. A development-PATH-only run
found another application's DLL and is not accepted as packaging evidence.
The official Microsoft ARM64 DXIL binary is separately pinned by archive,
file hash and release source commit in `runtime-build/dxc-arm64.lock.json`;
`prepare-dxc-arm64.py` extracts only that DLL and its three license notices.
It is an unmodified prebuilt Microsoft dependency, not compiled by the Mesa
recipe. Its binary license and public distribution approach remain a release
review item.
