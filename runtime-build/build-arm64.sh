#!/usr/bin/env bash
set -euo pipefail

if [[ ${MSYSTEM:-} != CLANGARM64 ]]; then
    echo "Build the ARM64 runtime in an MSYS2 CLANGARM64 shell" >&2
    exit 1
fi
export TRY_OMARCHY_RUNTIME_ARCH=arm64
exec "$(dirname "${BASH_SOURCE[0]}")/build.sh" "$@"
