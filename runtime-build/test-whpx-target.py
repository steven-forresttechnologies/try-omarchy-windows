#!/usr/bin/env python3
"""Compile the actual WHPX CPU class for x86 and non-x86 targets."""

import argparse
import os
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("source", type=Path)
args = parser.parse_args()
source = (args.source / "accel/whpx/whpx-common.c").read_text(encoding="utf-8")
if '#ifdef TARGET_I386\n#include "host-cpu.h"\n#endif' not in source:
    raise SystemExit("x86 host CPU header is not target-guarded")
start = source.index("static void whpx_cpu_accel_class_init(")
end = source.index("\n}\n", start) + 3
function = source[start:end]
fixture = r'''
#include <assert.h>
#include <stddef.h>
typedef struct ObjectClass { int unused; } ObjectClass;
typedef struct AccelCPUClass {
    void (*cpu_target_realize)(void);
    void (*cpu_instance_init)(void);
} AccelCPUClass;
static AccelCPUClass state;
#define ACCEL_CPU_CLASS(oc) (&state)
#ifdef TARGET_I386
static void host_cpu_realizefn(void) {}
#endif
static void whpx_cpu_instance_init(void) {}
''' + function + r'''
int main(void) {
    whpx_cpu_accel_class_init(NULL, NULL);
    assert(state.cpu_instance_init == whpx_cpu_instance_init);
#ifdef TARGET_I386
    assert(state.cpu_target_realize == host_cpu_realizefn);
#else
    assert(state.cpu_target_realize == NULL);
#endif
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix="whpx-target-") as directory:
    root = Path(directory)
    test = root / "test.c"
    test.write_text(fixture, encoding="utf-8")
    for target in ("i386", "arm"):
        exe = root / f"{target}.exe"
        flags = ["-DTARGET_I386"] if target == "i386" else ["-DTARGET_ARM"]
        subprocess.run([os.environ.get("CC", "cc"), "-std=c11", *flags, str(test), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
print("ok - WHPX uses the x86 host CPU hook only for x86 targets")
