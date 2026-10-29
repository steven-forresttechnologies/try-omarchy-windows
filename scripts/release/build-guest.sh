#!/usr/bin/env bash

set -euo pipefail

repo_root=$(cd "$(dirname "$0")/../.." && pwd)
output=""
contract_only=0
source_only=0
architecture=x86_64

while (($#)); do
  case "$1" in
    --architecture)
      [[ $# -ge 2 && -n ${2:-} ]] || { echo "--architecture requires a value" >&2; exit 2; }
      architecture=$2
      shift 2
      ;;
    --output)
      output=${2:-}
      shift 2
      ;;
    --contract-only)
      contract_only=1
      shift
      ;;
    --source-only)
      source_only=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

case "$architecture" in
  x86_64|amd64) architecture=x86_64 ;;
  aarch64) ;;
  *) echo "Unsupported guest architecture: $architecture" >&2; exit 2 ;;
esac

if ((contract_only == 0)) && [[ -z $output ]]; then
  echo "Usage: $0 --output DIR [--architecture x86_64|aarch64] [--contract-only | --source-only]" >&2
  exit 2
fi

# ARM artifacts currently share x86 filenames. Do not overwrite any existing
# contents; a fresh directory also keeps candidate release evidence separate.
if [[ $architecture == aarch64 ]] && ((contract_only == 0 && source_only == 0)); then
  [[ ! -L $output && ( ! -e $output || -d $output ) ]] || { echo "ARM output must be a new or empty directory" >&2; exit 2; }
  if [[ -d $output ]]; then
    existing=$(find "$output" -mindepth 1 -maxdepth 1 -print -quit) || { echo "Cannot inspect ARM output directory" >&2; exit 2; }
    [[ -z $existing ]] || { echo "ARM output must be a new or empty directory" >&2; exit 2; }
  fi
fi

# An AMD64 rerun may reuse its output, but never an ARM candidate's files.
if [[ $architecture == x86_64 && -d $output ]] && ((contract_only == 0 && source_only == 0)); then
  if ! python3 - "$output" <<'PYGUARD'
import json
from pathlib import Path
import sys

output = Path(sys.argv[1])
identified = False
for filename, section in (("build-spec.json", "image"), ("guest-manifest.json", "guest")):
    path = output / filename
    if path.is_symlink():
        raise SystemExit(f"refusing symlinked guest metadata: {path}")
    if not path.exists():
        continue
    try:
        architecture = json.loads(path.read_text())[section]["architecture"]
    except (OSError, ValueError, KeyError, TypeError):
        raise SystemExit(f"cannot identify guest architecture in {path}")
    if architecture != "x86_64":
        raise SystemExit(f"refusing to overwrite {architecture} guest artifacts in {output}")
    identified = True
if not identified:
    for filename in ("rootfs.ext4", "rootfs.ext4.zst", "vmlinuz-linux", "initramfs-linux.img", "SHA256SUMS"):
        path = output / filename
        if path.exists() or path.is_symlink():
            raise SystemExit(f"cannot identify existing guest artifacts in {output}")
PYGUARD
  then
    exit 2
  fi
fi

source_lock="$repo_root/guest-build/source.lock.json"
readarray -t source_fields < <(python3 - "$source_lock" <<'PY'
import json
import pathlib
import sys

lock = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
print(lock["repository"])
print(lock["commit"])
PY
)
source_url=${source_fields[0]}
source_commit=${source_fields[1]}
[[ $source_commit =~ ^[0-9a-f]{40}$ ]] || { echo "Invalid guest source commit" >&2; exit 1; }

work=$(mktemp -d "${RUNNER_TEMP:-/tmp}/try-omarchy-guest-source.XXXXXX")
cleanup() {
  rm -rf -- "$work"
}
trap cleanup EXIT

git -C "$work" init --quiet
git -C "$work" remote add origin "$source_url"
git -C "$work" fetch --quiet --depth=1 origin "$source_commit"
git -C "$work" checkout --quiet --detach FETCH_HEAD
test "$(git -C "$work" rev-parse HEAD)" = "$source_commit"
git -C "$work" config user.name "Try Omarchy Release"
git -C "$work" config user.email "actions@users.noreply.github.com"
git -C "$work" am "$repo_root"/guest-build/*.patch

# Export the patched builder without building an image or running its suites.
# The shell canary uses its own fetch, materialize and backport scripts.
if ((source_only)); then
  [[ -n $output && ! -e $output ]] || { echo "Source output must not exist" >&2; exit 2; }
  mkdir -p "$(dirname "$output")"
  mv -- "$work" "$output"
  exit 0
fi

# The guest carries the Try Omarchy importer from migrate/: try-omarchy-export
# runs it and packs it into every export. It is built here rather than kept in
# a patch so the guest and the release assets always ship the same code.
python3 "$repo_root/migrate/build.py" --version "${RELEASE_TAG:-dev}" --output "$work/importer" >/dev/null
install -Dm0755 "$work/importer/try-omarchy-import.pyz" \
  "$work/guest/factory-overlay/usr/local/lib/try-omarchy/try-omarchy-import.pyz"

"$work/guest/test"

if ((contract_only)); then
  exit 0
fi

mkdir -p "$output"
if [[ $architecture == aarch64 ]]; then
  sudo bash "$work/guest/build-container.sh" --spec "$work/guest/spec-aarch64.json" --output "$output"
else
  sudo bash "$work/guest/build-container.sh" --output "$output"
fi
# The container build runs as root so it can create and mount the factory
# filesystem. Return the finished release artifacts to the workflow user before
# later steps extend SHA256SUMS and upload the files.
sudo chown -R -- "$(id -u):$(id -g)" "$output"
