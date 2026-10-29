#!/usr/bin/env python3
"""Verify the runtime output before GitHub accepts it as an artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import zipfile
from pathlib import Path, PurePosixPath


REQUIRED = {
    "bin/qemu-system-x86_64.exe",
    "bin/qemu-system-x86_64w.exe",
    "bin/qemu-img.exe",
    "bin/libvirglrenderer-1.dll",
    "bin/SDL2.dll",
    "bin/libusb-1.0.dll",
    "bin/share/bios-256k.bin",
    "provenance/sources.lock.json",
    "provenance/runtime-manifest.json",
    "provenance/msys2-packages.txt",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_names(archive: zipfile.ZipFile) -> set[str]:
    names = archive.namelist()
    if len(names) != len(set(names)):
        raise SystemExit("archive contains duplicate paths")
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise SystemExit(f"archive contains unsafe path: {name}")
    return set(names)


def bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def verify_pe_machine(value: bytes, name: str, expected_machine: int) -> None:
    """Check PE32+ header bounds and the Windows binary's machine type."""
    if len(value) < 64 or value[:2] != b"MZ":
        raise SystemExit(f"{name} is not a Windows executable")
    pe_offset = struct.unpack_from("<I", value, 0x3C)[0]
    if pe_offset < 64 or pe_offset + 24 > len(value) or value[pe_offset:pe_offset + 4] != b"PE\0\0":
        raise SystemExit(f"{name} has an invalid PE header")
    machine = struct.unpack_from("<H", value, pe_offset + 4)[0]
    if machine != expected_machine:
        raise SystemExit(f"{name} has unexpected PE machine 0x{machine:04x}")
    sections = struct.unpack_from("<H", value, pe_offset + 6)[0]
    optional_size = struct.unpack_from("<H", value, pe_offset + 20)[0]
    optional_offset = pe_offset + 24
    if (optional_size < 112 or optional_offset + optional_size + sections * 40 > len(value)
            or struct.unpack_from("<H", value, optional_offset)[0] != 0x20B):
        raise SystemExit(f"{name} has an invalid PE32+ header")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--arch", choices=("amd64", "arm64"), default="amd64")
    args = parser.parse_args()
    suffix = "-arm64" if args.arch == "arm64" else ""
    runtime_path = args.output / f"winq-emu-alpha10-portable{suffix}.zip"
    source_path = args.output / f"winq-emu-alpha10-source{suffix}.zip"
    required = REQUIRED
    machine = 0x8664
    if args.arch == "arm64":
        required = (REQUIRED - {"bin/qemu-system-x86_64.exe", "bin/qemu-system-x86_64w.exe", "bin/share/bios-256k.bin"}) | {
            "bin/qemu-system-aarch64.exe", "bin/qemu-system-aarch64w.exe", "bin/share/edk2-aarch64-code.fd", "bin/vulkan-1.dll"
        }
        machine = 0xAA64

    mesa_lock = None
    dxc_lock = None
    with zipfile.ZipFile(runtime_path) as runtime:
        names = safe_names(runtime)
        missing = required - names
        if missing:
            raise SystemExit(f"runtime is missing: {', '.join(sorted(missing))}")
        if not any(name.startswith("LICENSES/qemu/") for name in names):
            raise SystemExit("runtime has no QEMU license")
        if not any(name.startswith("LICENSES/virglrenderer/") for name in names):
            raise SystemExit("runtime has no virglrenderer license")
        # A mixed-architecture runtime cannot load reliably. Check every
        # shipped binary, including qemu-img and collected dependency DLLs.
        for name in names:
            path = PurePosixPath(name)
            if path.parent == PurePosixPath("bin") and path.suffix.lower() in {".exe", ".dll", ".drv"}:
                verify_pe_machine(runtime.read(name), name, machine)
        lock = json.loads(runtime.read("provenance/sources.lock.json"))
        expected_lock = json.loads(
            Path(__file__).with_name("sources.lock.json").read_text(encoding="utf-8")
        )
        if lock != expected_lock:
            raise SystemExit("runtime source lock differs from the build recipe")
        manifest = json.loads(runtime.read("provenance/runtime-manifest.json"))
        if "provenance/mesa-arm64.lock.json" in names:
            if args.arch != "arm64":
                raise SystemExit("private ARM64 Mesa is in a non-ARM64 runtime")
            mesa_lock = json.loads(runtime.read("provenance/mesa-arm64.lock.json"))
            expected_mesa = json.loads(Path(__file__).with_name("mesa-arm64.lock.json").read_text(encoding="utf-8"))
            if mesa_lock != expected_mesa or manifest["sources"].get("mesa") != mesa_lock:
                raise SystemExit("ARM64 Mesa provenance differs from its source lock")
            mesa_files = {
                "bin/vulkan_dzn.dll", "bin/libspirv_to_dxil.dll", "bin/dzn-arm64.json",
                "LICENSES/mesa/license.rst", "LICENSES/DirectX-Headers/LICENSE",
                "provenance/mesa-build-options.json",
            }
            if mesa_files - names:
                raise SystemExit("ARM64 Mesa runtime or licensing is incomplete")
            icd = json.loads(runtime.read("bin/dzn-arm64.json"))
            if icd.get("ICD", {}).get("library_path") != "./vulkan_dzn.dll":
                raise SystemExit("ARM64 Mesa ICD does not select its private relative driver")
            for entry in mesa_lock["patches"]:
                path = f"provenance/{entry['file']}"
                if path not in names or bytes_sha256(runtime.read(path)) != entry["sha256"]:
                    raise SystemExit("ARM64 Mesa patch provenance is incomplete")
            if "provenance/dxc-arm64.lock.json" not in names:
                raise SystemExit("ARM64 Mesa is missing its private DXIL validator provenance")
            dxc_lock = json.loads(runtime.read("provenance/dxc-arm64.lock.json"))
            expected_dxc = json.loads(Path(__file__).with_name("dxc-arm64.lock.json").read_text(encoding="utf-8"))
            if dxc_lock != expected_dxc or manifest["sources"].get("dxc") != dxc_lock:
                raise SystemExit("ARM64 DXIL provenance differs from its release lock")
            for original, digest in dxc_lock["files"].items():
                destination = "bin/dxil.dll" if original == "bin/arm64/dxil.dll" else f"LICENSES/DirectXShaderCompiler/{original}"
                if destination not in names or bytes_sha256(runtime.read(destination)) != digest:
                    raise SystemExit(f"ARM64 DXIL validator or notice mismatch: {destination}")
        elif {"bin/vulkan_dzn.dll", "bin/libspirv_to_dxil.dll"} & names:
            raise SystemExit("Mesa binaries have no source provenance")
        if dxc_lock is None and {"bin/dxil.dll", "provenance/dxc-arm64.lock.json"} & names:
            raise SystemExit("DXIL files are outside the private ARM64 Mesa profile")
        for component in ("qemu", "virglrenderer"):
            if manifest["sources"][component]["commit"] != lock[component]["commit"]:
                raise SystemExit(f"{component} manifest does not match the source lock")
            patches = lock[component].get("patches", [])
            if manifest["sources"][component].get("patches", []) != patches:
                raise SystemExit(f"{component} manifest patches do not match the source lock")
            for entry in patches:
                shipped = f"provenance/{entry['file']}"
                if shipped not in names:
                    raise SystemExit(f"runtime provenance is missing {entry['file']}")
                if bytes_sha256(runtime.read(shipped)) != entry["sha256"]:
                    raise SystemExit(f"runtime provenance patch digest mismatch: {entry['file']}")
        described = set()
        for entry in manifest["files"]:
            name = entry["path"]
            if name in described or name not in names:
                raise SystemExit(f"manifest has an invalid file entry: {name}")
            described.add(name)
            value = runtime.read(name)
            if entry["size"] != len(value) or entry["sha256"] != bytes_sha256(value):
                raise SystemExit(f"manifest hash mismatch for {name}")
        expected_described = names - {"provenance/runtime-manifest.json"}
        if described != expected_described:
            raise SystemExit("manifest does not describe every runtime file")

    with zipfile.ZipFile(source_path) as source:
        names = safe_names(source)
        required_source_files = {
            "qemu/COPYING",
            "qemu/VERSION",
            "qemu/include/qemu/osdep.h",
            "virglrenderer/COPYING",
            "virglrenderer/meson.build",
            "build-recipe/archive.py",
            "build-recipe/build.sh",
            "build-recipe/sources.lock.json",
            "build-recipe/verify.py",
        }
        if mesa_lock is not None:
            required_source_files |= {
                "mesa/VERSION", "mesa/docs/license.rst", "mesa/meson.build",
                "mesa/src/microsoft/vulkan/dzn_device.c",
                "mesa/src/microsoft/vulkan/dzn_image.c",
                "mesa/subprojects/DirectX-Headers-1.0/LICENSE",
                "build-recipe/mesa-arm64.lock.json", "build-recipe/build-mesa-arm64.py",
                "build-recipe/dxc-arm64.lock.json", "build-recipe/prepare-dxc-arm64.py",
            }
        missing = required_source_files - names
        if missing:
            raise SystemExit(
                f"corresponding source archive is missing: {', '.join(sorted(missing))}"
            )
        source_lock = json.loads(source.read("build-recipe/sources.lock.json"))
        if source_lock != expected_lock:
            raise SystemExit("source archive lock differs from the build recipe")
        if mesa_lock is not None:
            if json.loads(source.read("build-recipe/mesa-arm64.lock.json")) != mesa_lock:
                raise SystemExit("Mesa corresponding source lock differs from the runtime")
            if source.read("mesa/VERSION").decode("utf-8").strip() != mesa_lock["version"]:
                raise SystemExit("Mesa corresponding source has the wrong version")
            if json.loads(source.read("build-recipe/dxc-arm64.lock.json")) != dxc_lock:
                raise SystemExit("DXIL corresponding recipe lock differs from the runtime")
            for entry in mesa_lock["patches"]:
                path = f"build-recipe/{entry['file']}"
                if path not in names or bytes_sha256(source.read(path)) != entry["sha256"]:
                    raise SystemExit("Mesa corresponding source is missing a locked patch")
        for component in ("qemu", "virglrenderer"):
            for entry in expected_lock[component].get("patches", []):
                shipped = f"build-recipe/{entry['file']}"
                if shipped not in names:
                    raise SystemExit(f"source archive is missing {entry['file']}")
                if bytes_sha256(source.read(shipped)) != entry["sha256"]:
                    raise SystemExit(
                        f"source archive patch digest mismatch: {entry['file']}"
                    )

    sums = {}
    for line in (args.output / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        # GNU coreutils uses a space followed by either another space for text
        # mode or an asterisk for binary mode. MSYS2 emits the latter for ZIPs.
        match = re.fullmatch(r"([0-9a-f]{64}) [ *]([^/]+)", line)
        if not match:
            raise SystemExit("SHA256SUMS has an invalid line")
        if match.group(2) in sums:
            raise SystemExit(f"SHA256SUMS has a duplicate entry for {match.group(2)}")
        sums[match.group(2)] = match.group(1)
    expected_sum_names = {runtime_path.name, source_path.name}
    if set(sums) != expected_sum_names:
        raise SystemExit("SHA256SUMS does not describe exactly the runtime and source archives")
    for path in (runtime_path, source_path):
        if sums.get(path.name) != sha256(path):
            raise SystemExit(f"SHA256 mismatch for {path.name}")

    print(f"ok - verified {len(required)} required {args.arch} runtime files and corresponding source")


if __name__ == "__main__":
    main()
