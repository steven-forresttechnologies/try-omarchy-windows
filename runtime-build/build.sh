#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "usage: $0 OUTPUT_DIRECTORY" >&2
    exit 2
fi

runtime_arch=${TRY_OMARCHY_RUNTIME_ARCH:-amd64}
case "$runtime_arch" in
    amd64) system=x86_64; mingw_prefix=/ucrt64; firmware=bios-256k.bin ;;
    arm64)
        [[ ${MSYSTEM:-} == CLANGARM64 ]] || { echo "ARM64 requires CLANGARM64" >&2; exit 1; }
        system=aarch64; mingw_prefix=/clangarm64; firmware=edk2-aarch64-code.fd ;;
    *) echo "Unsupported runtime architecture: $runtime_arch" >&2; exit 1 ;;
esac

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
recipe="$repo_root/runtime-build"
lock="$recipe/sources.lock.json"
output=$(mkdir -p "$1" && cd "$1" && pwd)
if [[ $runtime_arch == arm64 ]]; then
    other_runtime="$output/winq-emu-alpha10-portable.zip"
    other_source="$output/winq-emu-alpha10-source.zip"
else
    other_runtime="$output/winq-emu-alpha10-portable-arm64.zip"
    other_source="$output/winq-emu-alpha10-source-arm64.zip"
fi
if [[ -e $other_runtime || -e $other_source ]]; then
    echo "Use separate output directories for AMD64 and ARM64 runtimes" >&2
    exit 1
fi
if [[ -e "$output/smoke" ]]; then
    echo "Use a fresh output directory; smoke already exists" >&2
    exit 1
fi
temp_root=${RUNNER_TEMP:-/tmp}
if command -v cygpath >/dev/null 2>&1; then
    temp_root=$(cygpath -u "$temp_root")
fi
work=$(mktemp -d "$temp_root/try-omarchy-runtime.XXXXXX")
trap 'chmod -R u+w "$work" 2>/dev/null || true; rm -rf -- "$work"' EXIT

python "$recipe/validate-lock.py" "$lock"
if [[ $runtime_arch == arm64 ]]; then
    python "$recipe/test-collect-dlls-arm64.py"
fi

lock_value() {
    python - "$lock" "$1" "$2" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    value = json.load(source)
print(value[sys.argv[2]][sys.argv[3]])
PY
}

source_date_epoch=$(python - "$lock" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    print(json.load(source)["sourceDateEpoch"])
PY
)
# Native Windows Python writes CRLF even under MSYS2. Command substitution and
# read strip LF but can retain CR, which corrupts hashes and environment values.
source_date_epoch=${source_date_epoch%$'\r'}
export SOURCE_DATE_EPOCH="$source_date_epoch"
export TZ=UTC
export LC_ALL=C

clone_locked() {
    local name=$1
    local destination=$2
    local repository commit base
    repository=$(lock_value "$name" repository)
    commit=$(lock_value "$name" commit)
    base=$(lock_value "$name" baseCommit)
    repository=${repository%$'\r'}
    commit=${commit%$'\r'}
    base=${base%$'\r'}

    git init --quiet "$destination"
    git -C "$destination" remote add origin "$repository"
    git -C "$destination" fetch --quiet --depth=256 origin "$commit" "$base"
    git -C "$destination" checkout --quiet --detach "$commit"
    [[ $(git -C "$destination" rev-parse HEAD) == "$commit" ]]
    git -C "$destination" merge-base --is-ancestor "$base" "$commit" || {
        echo "$name commit is not based on its locked upstream commit" >&2
        exit 1
    }
}

apply_locked_patches() {
    local name=$1
    local destination=$2
    local relative digest
    while IFS=$'\t' read -r relative digest; do
        relative=${relative%$'\r'}
        digest=${digest%$'\r'}
        [[ -n "$relative" ]] || continue
        printf '%s  %s\n' "$digest" "$recipe/$relative" | sha256sum -c --quiet -
        git -C "$destination" apply --index "$recipe/$relative"
        echo "Applied $relative to $name"
    done < <(python - "$lock" "$name" <<'PATCHES'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    component = json.load(source)[sys.argv[2]]
for entry in component.get("patches", []):
    print(f"{entry['file']}\t{entry['sha256']}")
PATCHES
)
}

qemu_source="$work/qemu"
virgl_source="$work/virglrenderer"
clone_locked qemu "$qemu_source"
clone_locked virglrenderer "$virgl_source"
# Match QEMU's release process. Top-level ROM sources are included, and EDK2's
# direct dependencies are included separately. QEMU explicitly avoids a fully
# recursive EDK2 checkout because those dependencies do not use submodules of
# submodules; recursing downloads large unrelated trees such as pyca and krb5.
git -C "$qemu_source" submodule update --init --depth=1
git -C "$qemu_source/roms/edk2" submodule update --init --depth=1
apply_locked_patches qemu "$qemu_source"
apply_locked_patches virglrenderer "$virgl_source"
python "$recipe/test-win32-handles.py" "$virgl_source"
python "$recipe/test-host-memory.py" "$virgl_source"
python "$recipe/test-image-capabilities.py" "$virgl_source"
python "$recipe/test-resource-shim.py" "$virgl_source"
python "$recipe/test-proxy-resource-reply.py" "$virgl_source"
python "$recipe/test-buffer-upload.py" "$virgl_source"
python "$recipe/test-usb-port.py" "$qemu_source/hw/usb/host-libusb.c"
python "$recipe/test-socket-close.py" "$qemu_source/util/oslib-win32.c"
python "$recipe/test-fd-setsize.py" "$qemu_source"
python "$recipe/test-file-drop.py" "$qemu_source/ui/sdl2.c"
python "$recipe/test-windows-share.py" "$qemu_source/hw/9pfs/9p-util-win32.c"
python "$recipe/test-sdl-scanout.py" "$qemu_source/ui/sdl2-gl.c"
python "$recipe/test-sdl-input.py" "$qemu_source/ui/sdl2.c"
python "$recipe/test-whpx-cpu-model.py" "$qemu_source"
python "$recipe/test-whpx-target.py" "$qemu_source"
python "$recipe/test-sdl-keyboard-hook.py" "$qemu_source"
python "$recipe/test-sdl-scroll.py" "$qemu_source"
python "$recipe/test-virtio-scroll.py" "$qemu_source"
python "$recipe/test-sdl-cursor.py" "$qemu_source"
python "$recipe/test-sdl-context.py" "$qemu_source/ui/sdl2.c"
python "$recipe/test-sdl-audio.py" "$qemu_source/audio/sdlaudio.c"
python "$recipe/test-sdl-capture.py" "$qemu_source"
python "$recipe/test-windows-pinch.py"
python "$qemu_source/scripts/qapi-gen.py" -o "$work/qapi-validation" -b "$qemu_source/qapi/qapi-schema.json"

virgl_build="$work/virgl-build"
virgl_prefix=$mingw_prefix
if [[ $runtime_arch == arm64 ]]; then
    # Never overwrite packages in the developer's MSYS2 installation.
    virgl_prefix=$(cygpath -m "$work/virgl-prefix")
    export PKG_CONFIG_PATH="$virgl_prefix/lib/pkgconfig${PKG_CONFIG_PATH:+;$PKG_CONFIG_PATH}"
fi
meson setup "$virgl_build" "$virgl_source" \
    --buildtype=release \
    --prefix="$virgl_prefix" \
    -Dvenus=true \
    -Dvideo=true \
    -Dtests=false
meson compile -C "$virgl_build"
meson install -C "$virgl_build"

mesa_root=""
if [[ $runtime_arch == arm64 ]]; then
    mesa_root="$work/mesa"
    python "$recipe/build-mesa-arm64.py" "$mesa_root"
fi

qemu_build="$work/qemu-build"
mkdir -p "$qemu_build"
qemu_extra=()
if [[ $runtime_arch == arm64 ]]; then
    # This engineering build uses the project's guest agent, not qga. Clang
    # 23 reports upstream unused globals; do not hide that this is a candidate.
    qemu_extra=(--disable-guest-agent --disable-werror)
fi
(
    cd "$qemu_build"
    "$qemu_source/configure" \
        --target-list="$system-softmmu" \
        --prefix="$mingw_prefix" \
        --enable-whpx \
        --enable-opengl \
        --enable-virglrenderer \
        --enable-slirp \
        --enable-libusb \
        --disable-docs \
        --disable-plugins "${qemu_extra[@]}"
)
meson compile -C "$qemu_build"

stage="$work/install"
DESTDIR="$stage" meson install -C "$qemu_build"
installed_windowless=$(find "$stage" -type f -name "qemu-system-${system}w.exe" -print -quit)
[[ -n "$installed_windowless" ]] || {
    echo "QEMU install did not produce qemu-system-${system}w.exe" >&2
    exit 1
}
installed_bin=$(dirname "$installed_windowless")
installed_firmware=$(find "$stage" -type f -name "$firmware" -print -quit)
[[ -n "$installed_firmware" ]] || {
    echo "QEMU install did not produce $firmware" >&2
    exit 1
}
installed_share=$(dirname "$installed_firmware")
runtime="$work/runtime"
mkdir -p "$runtime/bin/share" "$runtime/LICENSES/qemu" \
    "$runtime/LICENSES/virglrenderer" "$runtime/LICENSES/msys2" \
    "$runtime/provenance"

for binary in "qemu-system-${system}.exe" "qemu-system-${system}w.exe" qemu-img.exe; do
    [[ -f "$installed_bin/$binary" ]] || {
        echo "QEMU install did not produce $binary" >&2
        exit 1
    }
    cp "$installed_bin/$binary" "$runtime/bin/"
done
[[ -d "$installed_share" ]] || {
    echo "QEMU install did not produce its firmware directory" >&2
    exit 1
}
cp -R "$installed_share/." "$runtime/bin/share/"
cp "$virgl_prefix/bin/libvirglrenderer-1.dll" "$runtime/bin/"
if [[ $runtime_arch == arm64 ]]; then
    cp "$mesa_root/build/src/microsoft/vulkan/vulkan_dzn.dll" "$runtime/bin/"
    cp "$mesa_root/build/src/microsoft/spirv_to_dxil/libspirv_to_dxil.dll" "$runtime/bin/"
    python "$recipe/prepare-dxc-arm64.py" "$work/dxc"
    cp "$work/dxc/dxil.dll" "$runtime/bin/"
    cp "$recipe/dxc-arm64.lock.json" "$runtime/provenance/"
    cp "$recipe/mesa-arm64.lock.json" "$runtime/provenance/"
    cp "$mesa_root/build-options.json" "$runtime/provenance/mesa-build-options.json"
    python - "$mesa_root" "$runtime" <<'ICD'
import json
from pathlib import Path
import sys

mesa, runtime = map(Path, sys.argv[1:])
icd = json.loads((mesa / 'build/src/microsoft/vulkan/dzn_devenv_icd.aarch64.json').read_text(encoding='utf-8'))
icd['ICD']['library_path'] = './vulkan_dzn.dll'
(runtime / 'bin/dzn-arm64.json').write_text(json.dumps(icd, indent=2) + '\n', encoding='utf-8')
ICD
    mkdir -p "$runtime/LICENSES/mesa" "$runtime/LICENSES/DirectX-Headers"
    cp "$mesa_root/source/docs/license.rst" "$runtime/LICENSES/mesa/"
    cp "$mesa_root/source/subprojects/DirectX-Headers-1.0/LICENSE" "$runtime/LICENSES/DirectX-Headers/"
    mkdir -p "$runtime/LICENSES/DirectXShaderCompiler"
    cp "$work/dxc/LICENCE-MIT.txt" "$work/dxc/LICENSE-LLVM.txt" "$work/dxc/LICENSE-MS.txt" \
        "$runtime/LICENSES/DirectXShaderCompiler/"
fi

echo "Collecting runtime DLLs"
if [[ $runtime_arch == arm64 ]]; then
    python "$recipe/collect-dlls-arm64.py" "$runtime/bin" "$runtime/provenance/dll-sources.txt" "$mingw_prefix"
else
    "$recipe/collect-dlls.sh" "$runtime/bin" "$runtime/provenance/dll-sources.txt"
fi

for license in COPYING COPYING.LIB LICENSE; do
    [[ -f "$qemu_source/$license" ]] || {
        echo "QEMU source is missing $license" >&2
        exit 1
    }
    cp "$qemu_source/$license" "$runtime/LICENSES/qemu/$license"
done
[[ -f "$virgl_source/COPYING" ]] || {
    echo "virglrenderer source is missing COPYING" >&2
    exit 1
}
cp "$virgl_source/COPYING" "$runtime/LICENSES/virglrenderer/COPYING"
echo "Collected project licenses"

used_packages="$runtime/provenance/msys2-packages.txt"
: >"$used_packages"
while IFS= read -r source_path; do
    source_path=${source_path%$'\r'}
    [[ -n "$source_path" ]] || continue
    owner=$(pacman -Qoq "$source_path" 2>/dev/null || true)
    if [[ -z "$owner" || "$owner" == *$'\n'* ]]; then
        echo "Could not resolve one package owner for $source_path" >&2
        exit 1
    fi
    package_line=$(pacman -Q "$owner" 2>/dev/null || true)
    if [[ -z "$package_line" ]]; then
        echo "Could not read the package version for $owner" >&2
        exit 1
    fi
    printf '%s\n' "$package_line" >>"$used_packages"
done <"$runtime/provenance/dll-sources.txt"
sort -u -o "$used_packages" "$used_packages"

echo "Collecting dependency licenses"
while read -r package _version; do
    license_root="$runtime/LICENSES/msys2/$package"
    while IFS= read -r license_path; do
        [[ -f "$license_path" ]] || continue
        relative=${license_path#*/share/licenses/}
        mkdir -p "$license_root/$(dirname "$relative")"
        cp "$license_path" "$license_root/$relative"
    done < <(pacman -Qql "$package" | grep '/share/licenses/' || true)
done <"$used_packages"
echo "Collected licenses for $(wc -l <"$used_packages") runtime packages"

cp "$lock" "$runtime/provenance/sources.lock.json"
if [[ -d "$recipe/patches" ]]; then
    mkdir -p "$runtime/provenance/patches"
    cp -R "$recipe/patches/." "$runtime/provenance/patches/"
fi
pacman -Q | sort >"$runtime/provenance/build-environment-packages.txt"
cat >"$runtime/README.txt" <<'EOF'
WINQ-EMU runtime for Try Omarchy

This portable runtime contains the patched QEMU and virglrenderer components
used by Try Omarchy. Exact source commits, binary hashes, dependency versions,
and licenses are included under provenance and LICENSES.

The corresponding source archive is published beside this runtime artifact.
EOF
if [[ $runtime_arch == arm64 ]]; then
    cat >>"$runtime/README.txt" <<'EOF'

The private Dozen ICD also uses an unmodified prebuilt Microsoft DXIL validator.
Its separate binary terms and MIT/LLVM notices are in LICENSES/DirectXShaderCompiler;
its release archive, file hashes and source commit are in provenance/dxc-arm64.lock.json.
This is a local engineering candidate. Public distribution requires license review.
EOF
fi

source_bundle="$work/source"
echo "Preparing corresponding source"
mkdir -p "$source_bundle/qemu" "$source_bundle/virglrenderer" \
    "$source_bundle/build-recipe"
tar -C "$qemu_source" --exclude=.git --exclude='*/.git' -cf - . | \
    tar -C "$source_bundle/qemu" -xf -
tar -C "$virgl_source" --exclude=.git --exclude='*/.git' -cf - . | \
    tar -C "$source_bundle/virglrenderer" -xf -
if [[ $runtime_arch == arm64 ]]; then
    mkdir -p "$source_bundle/mesa"
    tar -C "$mesa_root/source" --exclude=.git --exclude='*/.git' -cf - . | \
        tar -C "$source_bundle/mesa" -xf -
fi
cp "$recipe"/*.py "$recipe"/*.sh "$recipe"/*.json "$recipe"/*.txt "$recipe"/*.c \
    "$source_bundle/build-recipe/"
if [[ -d "$recipe/patches" ]]; then
    cp -R "$recipe/patches" "$source_bundle/build-recipe/patches"
fi

manifest="$runtime/provenance/runtime-manifest.json"
echo "Creating runtime archives"
python "$recipe/manifest.py" "$runtime" "$lock" "$used_packages" "$manifest"
archive_suffix=""
[[ $runtime_arch != arm64 ]] || archive_suffix="-arm64"
runtime_zip="$output/winq-emu-alpha10-portable${archive_suffix}.zip"
source_zip="$output/winq-emu-alpha10-source${archive_suffix}.zip"
python "$recipe/archive.py" "$runtime" "$runtime_zip" --epoch "$source_date_epoch"
python "$recipe/archive.py" "$source_bundle" "$source_zip" --epoch "$source_date_epoch"
(
    cd "$output"
    sha256sum "$(basename "$runtime_zip")" "$(basename "$source_zip")" >SHA256SUMS
)

python "$recipe/verify.py" "$output" --arch "$runtime_arch"
# Exercise the verified ZIP's exact contents in a fresh directory. A stale DLL
# in an old smoke directory must not make an incomplete archive appear valid.
python -m zipfile -e "$runtime_zip" "$work/extracted"
cp -R "$work/extracted/bin" "$output/smoke"
echo "Built $(du -h "$runtime_zip" | cut -f1) runtime and $(du -h "$source_zip" | cut -f1) source archive"
