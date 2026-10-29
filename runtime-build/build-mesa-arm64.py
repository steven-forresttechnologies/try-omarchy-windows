#!/usr/bin/env python3
"""Build the private ARM64 Dozen ICD from reviewed, pinned sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import tarfile


RECIPE = Path(__file__).resolve().parent
OPTIONS = [
    "--buildtype=release", "--wrap-mode=nodownload",
    "--force-fallback-for=DirectX-Headers", "-Dplatforms=windows",
    "-Dgallium-drivers=", "-Dvulkan-drivers=microsoft-experimental",
    "-Dllvm=disabled", "-Dgles1=disabled", "-Dgles2=disabled", "-Dopengl=false",
    "-Dglx=disabled", "-Degl=disabled", "-Dgbm=disabled",
    "-Dmicrosoft-clc=disabled", "-Dbuild-tests=false",
]


def validate() -> dict:
    lock = json.loads((RECIPE / "mesa-arm64.lock.json").read_text(encoding="utf-8"))
    if set(lock) != {"schema", "version", "url", "sha256", "license", "directxHeaders", "patches"} or lock["schema"] != 1:
        raise SystemExit("unsupported ARM64 Mesa source lock")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", lock["version"]):
        raise SystemExit("invalid Mesa version")
    if lock["url"] != f"https://archive.mesa3d.org/mesa-{lock['version']}.tar.xz":
        raise SystemExit("Mesa must come from its official HTTPS release archive")
    if not re.fullmatch(r"[0-9a-f]{64}", lock["sha256"]):
        raise SystemExit("invalid Mesa archive hash")
    headers = lock["directxHeaders"]
    if (set(headers) != {"repository", "commit", "license"}
            or headers["repository"] != "https://github.com/microsoft/DirectX-Headers.git"
            or not re.fullmatch(r"[0-9a-f]{40}", headers["commit"])):
        raise SystemExit("invalid DirectX-Headers source lock")
    runpy.run_path(str(RECIPE / "validate-lock.py"))["validate_patches"](
        "mesa", lock["patches"], RECIPE
    )
    return lock


def run(*arguments: str, cwd: Path | None = None) -> None:
    subprocess.run(arguments, cwd=cwd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, nargs="?")
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    lock = validate()
    if args.validate:
        print(f"ok - locked Mesa {lock['version']} and DirectX-Headers {lock['directxHeaders']['commit'][:12]}")
        return
    if args.destination is None or os.environ.get("MSYSTEM") != "CLANGARM64":
        parser.error("provide a fresh destination in a native CLANGARM64 shell")
    destination = args.destination.resolve()
    destination.mkdir()  # Refuse an existing checkout or build directory.
    archive = destination / "mesa.tar.xz"
    run("curl", "--fail", "--location", "--retry", "3", "--proto", "=https",
        "--proto-redir", "=https", "--output", str(archive), lock["url"])
    # Hash before extracting or executing anything from the archive.
    with archive.open("rb") as downloaded:
        digest = hashlib.file_digest(downloaded, "sha256").hexdigest()
    if digest != lock["sha256"]:
        raise SystemExit("Mesa source archive checksum mismatch")
    unpack = destination / "unpack"
    unpack.mkdir()
    with tarfile.open(archive) as tar:
        prefix = f"mesa-{lock['version']}/"
        if any(not (entry.name == prefix[:-1] or entry.name.startswith(prefix)) for entry in tar):
            raise SystemExit("Mesa archive has an unexpected source root")
        tar.extractall(unpack, filter="data")
    source = destination / "source"
    (unpack / f"mesa-{lock['version']}").rename(source)
    for patch in lock["patches"]:
        run("git", "apply", "--check", str(RECIPE / patch["file"]), cwd=source)
        run("git", "apply", str(RECIPE / patch["file"]), cwd=source)

    headers = source / "subprojects" / "DirectX-Headers-1.0"
    headers.mkdir()
    run("git", "init", "--quiet", str(headers))
    run("git", "remote", "add", "origin", lock["directxHeaders"]["repository"], cwd=headers)
    commit = lock["directxHeaders"]["commit"]
    run("git", "fetch", "--quiet", "--depth=1", "origin", commit, cwd=headers)
    run("git", "checkout", "--quiet", "--detach", commit, cwd=headers)
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=headers, text=True).strip()
    if actual != commit:
        raise SystemExit("DirectX-Headers checkout does not match its pin")

    build = destination / "build"
    run("meson", "setup", str(build), str(source), *OPTIONS)
    run("meson", "compile", "-C", str(build))
    (destination / "build-options.json").write_text(
        json.dumps({"mesonOptions": OPTIONS}, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Built private ARM64 Mesa {lock['version']} in {destination}")


if __name__ == "__main__":
    main()
