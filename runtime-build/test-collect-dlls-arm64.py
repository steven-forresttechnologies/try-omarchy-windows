#!/usr/bin/env python3
"""Exercise the ARM64 collector's PE directory and dependency checks."""
import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("collector", Path(__file__).with_name("collect-dlls-arm64.py"))
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


def pe(*, count=16, delay=(0, 0)):
    data = bytearray(512)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 64)
    data[64:68] = b"PE\0\0"
    struct.pack_into("<H", data, 68, 0xAA64)
    struct.pack_into("<H", data, 84, 240)
    struct.pack_into("<H", data, 88, 0x20B)
    struct.pack_into("<I", data, 88 + 108, count)
    struct.pack_into("<II", data, 88 + 112 + 13 * 8, *delay)
    return bytes(data)


class CollectorTest(unittest.TestCase):
    def test_package_owner_paths_have_lf_line_endings(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "sources.txt"
            collector.write_sources(output, "/clangarm64", [Path("a.dll")])
            self.assertEqual(output.read_bytes(), b"/clangarm64/bin/a.dll\n")

    def test_rejects_delay_imports_and_truncated_directories(self):
        self.assertEqual(collector.directories(pe(), "test"), (0, 0))
        for data in (pe(delay=(1, 1)), pe(count=17)):
            with self.assertRaises(SystemExit):
                collector.directories(data, "test")

    def test_rejects_dll_found_only_outside_allowed_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "bin").mkdir()
            (root / "prefix" / "bin").mkdir(parents=True)
            (root / "prefix" / "bin" / "vulkan-1.dll").write_bytes(pe())
            (root / "windows" / "System32").mkdir(parents=True)
            (root / "bin" / "qemu.exe").write_bytes(pe())
            outside = root / "outside"
            outside.mkdir()
            (outside / "foreign.dll").write_bytes(pe())
            result = type("Result", (), {"stdout": "    DLL Name: foreign.dll\n"})()
            argv = ["collector", str(root / "bin"), str(root / "sources"), str(root / "prefix")]
            with patch.object(sys, "argv", argv), patch.dict(collector.os.environ, {"WINDIR": str(root / "windows"), "PATH": str(outside)}), patch.object(collector.subprocess, "run", return_value=result):
                with self.assertRaisesRegex(SystemExit, "unresolved non-system DLL"):
                    collector.main()

    def test_does_not_skip_malformed_name_among_valid_imports(self):
        output = "    DLL Name: KERNEL32.dll\n    DLL Name: bad name.dll\n    DLL Name:\n"
        names = collector.IMPORT.findall(output)
        self.assertEqual(names, ["KERNEL32.dll", "bad name.dll", ""])
        self.assertIsNone(collector.DLL.fullmatch(names[1]))
        self.assertIsNone(collector.DLL.fullmatch(names[2]))


if __name__ == "__main__":
    unittest.main()
