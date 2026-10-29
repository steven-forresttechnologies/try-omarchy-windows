#!/usr/bin/env bash
set -euo pipefail
recipe=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
for arch in amd64 arm64; do
    mkdir -p "$work/$arch"
    if [[ $arch == amd64 ]]; then
        touch "$work/$arch/winq-emu-alpha10-portable-arm64.zip"
    else
        touch "$work/$arch/winq-emu-alpha10-portable.zip"
    fi
    if MSYSTEM=CLANGARM64 TRY_OMARCHY_RUNTIME_ARCH=$arch \
        bash "$recipe/build.sh" "$work/$arch" >"$work/log" 2>&1; then
        echo "build accepted mixed architecture output for $arch" >&2
        exit 1
    fi
    grep -F 'Use separate output directories' "$work/log" >/dev/null
done
mkdir -p "$work/stale/smoke"
if MSYSTEM=CLANGARM64 TRY_OMARCHY_RUNTIME_ARCH=arm64 \
    bash "$recipe/build.sh" "$work/stale" >"$work/log" 2>&1; then
    echo "build accepted a stale smoke directory" >&2
    exit 1
fi
grep -F 'smoke already exists' "$work/log" >/dev/null
echo "ok - mixed architecture output directories are rejected"
