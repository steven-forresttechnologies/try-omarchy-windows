#!/usr/bin/env python3
"""Collect ARM64 PE imports without loading untrusted DLLs into a process."""

import argparse
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess

from verify import verify_pe_machine

DLL = re.compile(r"^[A-Za-z0-9_.+-]+\.(?:dll|drv)$", re.IGNORECASE)
IMPORT = re.compile(r"^[ \t]*DLL Name:[ \t]*([^\r\n]*?)[ \t]*$", re.MULTILINE)


def write_sources(path: Path, prefix_posix: str, sources: list[Path]) -> None:
    path.write_text("".join(f"{prefix_posix}/bin/{p.name}\n" for p in sorted(sources, key=lambda p: p.name.lower())), encoding="utf-8", newline="\n")


def directories(value: bytes, name: str) -> tuple[int, int]:
    verify_pe_machine(value, name, 0xAA64)
    pe = struct.unpack_from("<I", value, 0x3C)[0]
    optional = pe + 24
    size = struct.unpack_from("<H", value, pe + 20)[0]
    count = struct.unpack_from("<I", value, optional + 108)[0]
    if count > (size - 112) // 8:
        raise SystemExit(f"{name} has truncated PE data directories")
    if count > 13:
        delay_rva, delay_size = struct.unpack_from("<II", value, optional + 112 + 13 * 8)
        if delay_rva or delay_size:
            raise SystemExit(f"{name} has unsupported delay-load imports")
    if count > 1:
        return struct.unpack_from("<II", value, optional + 112 + 8)
    return 0, 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bin", type=Path)
    parser.add_argument("sources", type=Path)
    parser.add_argument("prefix", type=Path)
    args = parser.parse_args()
    bindir = args.bin.resolve(strict=True)
    prefix = args.prefix.resolve(strict=True)
    system = Path(os.environ["WINDIR"]) / "System32"
    seen = set()
    copied = {}
    queue = list(bindir.glob("*.exe")) + list(bindir.glob("*.dll"))
    # The patched renderer loads this dynamically, so it is absent from PE
    # imports. Ship the native loader and walk its own imports as well.
    vulkan = prefix / "bin" / "vulkan-1.dll"
    if not vulkan.is_file():
        raise SystemExit("CLANGARM64 Vulkan loader is missing")
    verify_pe_machine(vulkan.read_bytes(), str(vulkan), 0xAA64)
    destination = bindir / vulkan.name
    if destination.exists():
        raise SystemExit("Runtime already contains vulkan-1.dll")
    shutil.copyfile(vulkan, destination)
    copied[vulkan.name.lower()] = vulkan
    queue.append(destination)
    while queue:
        path = queue.pop()
        key = path.name.lower()
        if key in seen:
            continue
        seen.add(key)
        import_rva, import_size = directories(path.read_bytes(), str(path))
        result = subprocess.run(["llvm-objdump", "-p", str(path)], capture_output=True, text=True, check=True)
        names = IMPORT.findall(result.stdout)
        if (import_rva or import_size) and not names:
            raise SystemExit(f"{path} has an import directory but no readable imports")
        for name in names:
            if not DLL.fullmatch(name):
                raise SystemExit(f"Invalid DLL import in {path}: {name}")
            lower = name.lower()
            if lower.startswith(("api-ms-win-", "ext-ms-win-")):
                continue  # Windows API-set loader contracts are not files.
            existing = bindir / name
            source = prefix / "bin" / name
            if existing.is_file():
                queue.append(existing)
            elif source.is_file():
                verify_pe_machine(source.read_bytes(), str(source), 0xAA64)
                shutil.copyfile(source, existing)
                copied[lower] = source
                queue.append(existing)
            elif not (system / name).is_file():
                raise SystemExit(f"{path} imports unresolved non-system DLL {name}")
    if not copied:
        raise SystemExit("No CLANGARM64 runtime dependencies were collected")
    prefix_posix = subprocess.check_output(["cygpath", "-u", str(prefix)], text=True).strip()
    write_sources(args.sources, prefix_posix, list(copied.values()))
    print(f"Collected {len(copied)} CLANGARM64 DLL dependencies")


if __name__ == "__main__":
    main()
