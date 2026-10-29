#!/usr/bin/env python3
"""Prepare the pinned, unmodified Microsoft ARM64 DXIL validator and notices."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

from verify import verify_pe_machine


RECIPE = Path(__file__).resolve().parent
FILES = {"bin/arm64/dxil.dll", "LICENCE-MIT.txt", "LICENSE-LLVM.txt", "LICENSE-MS.txt"}


def validate() -> dict:
    lock = json.loads((RECIPE / "dxc-arm64.lock.json").read_text(encoding="utf-8"))
    if (set(lock) != {"schema", "version", "repository", "commit", "url", "sha256", "license", "files"}
            or lock["schema"] != 1 or set(lock["files"]) != FILES):
        raise SystemExit("unsupported ARM64 DXC lock")
    if (lock["repository"] != "https://github.com/microsoft/DirectXShaderCompiler"
            or not re.fullmatch(r"[0-9a-f]{40}", lock["commit"])
            or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", lock["version"])
            or not re.fullmatch(
                re.escape(lock["repository"] + "/releases/download/v" + lock["version"])
                + r"/dxc_[0-9]{4}_[0-9]{2}_[0-9]{2}\.zip", lock["url"])):
        raise SystemExit("DXC must use its official pinned HTTPS release")
    if any(not re.fullmatch(r"[0-9a-f]{64}", value)
           for value in [lock["sha256"], *lock["files"].values()]):
        raise SystemExit("invalid DXC hash")
    return lock


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", nargs="?", type=Path)
    parser.add_argument("--archive", type=Path, help="optional local archive, still hash-verified")
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    lock = validate()
    if args.validate:
        print(f"ok - locked Microsoft ARM64 DXIL {lock['version']}")
        return
    if args.destination is None:
        parser.error("provide a fresh destination")
    args.destination.mkdir()
    archive = args.archive
    if archive is None:
        archive = args.destination / "dxc.zip"
        subprocess.run([
            "curl", "--fail", "--location", "--retry", "3", "--proto", "=https",
            "--proto-redir", "=https", "--output", str(archive), lock["url"],
        ], check=True)
    with archive.open("rb") as downloaded:
        if hashlib.file_digest(downloaded, "sha256").hexdigest() != lock["sha256"]:
            raise SystemExit("DXC archive checksum mismatch")
    with zipfile.ZipFile(archive) as source:
        if len(source.namelist()) != len(set(source.namelist())):
            raise SystemExit("duplicate DXC archive names")
        for name, digest in lock["files"].items():
            entry = source.getinfo(name)
            if entry.file_size > 32 << 20 or entry.is_dir():
                raise SystemExit("unexpected DXC file")
            value = source.read(entry)
            if hashlib.sha256(value).hexdigest() != digest:
                raise SystemExit(f"DXC file checksum mismatch: {name}")
            if name.endswith(".dll"):
                verify_pe_machine(value, name, 0xAA64)
            (args.destination / Path(name).name).write_bytes(value)
    print(f"Prepared Microsoft ARM64 DXIL {lock['version']} with its notices")


if __name__ == "__main__":
    main()
