#!/usr/bin/env python3
"""Probe ARM64 WHPX migration boundaries with a paused, diskless VM.

This does not establish saved-session support: no guest OS runs and no incoming
restore is attempted. All RAM transferred to the loopback receiver is discarded.
"""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time

from verify import verify_pe_machine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("qemu", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("requires Windows ARM64 and WHPX")
    qemu = args.qemu.resolve(strict=True)
    verify_pe_machine(qemu.read_bytes(), str(qemu), 0xAA64)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        qmp_port = reservation.getsockname()[1]
    receiver = socket.socket()
    receiver.bind(("127.0.0.1", 0))
    receiver.listen(1)
    receiver.settimeout(5)
    transferred = [0]

    def drain() -> None:
        try:
            conn, _ = receiver.accept()
            with conn:
                conn.settimeout(5)
                while data := conn.recv(65536):
                    transferred[0] += len(data)
        except (OSError, TimeoutError):
            pass

    worker = threading.Thread(target=drain, daemon=True)
    worker.start()
    report = {"scope": "paused diskless outgoing-only probe", "architecture": "aarch64"}
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("VK_")}
    windows = os.environ["SystemRoot"]
    env["PATH"] = str(Path(windows) / "System32") + ";" + windows
    with tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen([
            str(qemu), "-machine", "virt,accel=whpx", "-cpu", "host", "-m", "256",
            "-nodefaults", "-display", "none", "-S", "-qmp",
            f"tcp:127.0.0.1:{qmp_port},server=on,wait=off",
        ], cwd=qemu.parent, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW)
        conn = None
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                try:
                    conn = socket.create_connection(("127.0.0.1", qmp_port), .5)
                    break
                except OSError:
                    if process.poll() is not None:
                        raise RuntimeError(f"QEMU exited {process.returncode}")
                    time.sleep(.1)
            if conn is None:
                raise TimeoutError("QMP startup deadline")
            conn.settimeout(5)
            stream = conn.makefile("rb")
            report["greeting"] = json.loads(stream.readline())
            request_id = 0

            def call(command: str, arguments: dict | None = None) -> dict:
                nonlocal request_id
                request_id += 1
                payload = {"execute": command, "id": request_id}
                if arguments is not None:
                    payload["arguments"] = arguments
                conn.sendall((json.dumps(payload) + "\n").encode())
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    reply = json.loads(stream.readline())
                    if reply.get("id") == request_id:
                        return reply
                raise TimeoutError(f"QMP {command} deadline")

            report["capabilities"] = call("qmp_capabilities")
            report["state"] = call("query-status")
            report["before"] = call("query-migrate")
            report["request"] = call("migrate", {
                "uri": f"tcp:127.0.0.1:{receiver.getsockname()[1]}",
            })
            if "error" not in report["request"]:
                for _ in range(30):
                    report["after"] = call("query-migrate")
                    if report["after"].get("return", {}).get("status") in {"completed", "failed", "cancelled"}:
                        break
                    time.sleep(.1)
                else:
                    report["cancel"] = call("migrate_cancel")
            report["quit"] = call("quit")
            process.wait(timeout=5)
        finally:
            if conn is not None:
                conn.close()
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            receiver.close()
            worker.join(timeout=6)
            report["exit"] = process.returncode
            report["streamBytes"] = transferred[0]
            stderr.seek(0)
            report["stderr"] = stderr.read().decode("utf-8", "replace")
            args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
