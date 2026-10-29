#!/usr/bin/env python3
"""Check runtime binary architecture validation without a Windows host."""

import struct
import unittest

from verify import verify_pe_machine


def pe(machine):
    value = bytearray(512)
    value[:2] = b"MZ"
    struct.pack_into("<I", value, 0x3C, 64)
    value[64:68] = b"PE\0\0"
    struct.pack_into("<H", value, 68, machine)
    struct.pack_into("<H", value, 70, 1)  # section count
    struct.pack_into("<H", value, 84, 240)  # optional header length
    struct.pack_into("<H", value, 88, 0x20B)  # PE32+
    return bytes(value)


class MachineTest(unittest.TestCase):
    def test_matches_expected_machine(self):
        verify_pe_machine(pe(0x8664), "qemu.exe", 0x8664)
        verify_pe_machine(pe(0xAA64), "qemu.exe", 0xAA64)

    def test_rejects_wrong_or_invalid_headers(self):
        for value in (pe(0xAA64), b"MZ", b"not a PE", pe(0x8664)[:70], pe(0x8664)[:327]):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                verify_pe_machine(value, "qemu.exe", 0x8664)
        malformed = bytearray(pe(0x8664))
        struct.pack_into("<I", malformed, 0x3C, 0xFFFFFFFF)
        with self.assertRaises(SystemExit):
            verify_pe_machine(bytes(malformed), "qemu.exe", 0x8664)


if __name__ == "__main__":
    unittest.main()
