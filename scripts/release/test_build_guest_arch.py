"""Exercise release guest architecture routing without network or Docker."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("build-guest.sh")
COMMIT = "a" * 40


@unittest.skipUnless(shutil.which("bash"), "bash is required")
class BuildGuestArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "scripts/release").mkdir(parents=True)
        (self.root / "guest-build").mkdir()
        (self.root / "migrate").mkdir()
        (self.root / "bin").mkdir()
        self.script = self.root / "scripts/release/build-guest.sh"
        # Universal newline conversion also permits running against a Windows checkout.
        self.script.write_text(SCRIPT.read_text())
        (self.root / "guest-build/source.lock.json").write_text(json.dumps({
            "repository": "https://example.invalid/guest.git", "commit": COMMIT,
        }))
        (self.root / "guest-build/0001.patch").write_text("fixture")
        (self.root / "migrate/build.py").write_text(
            "import pathlib, sys\n"
            "p = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])\n"
            "p.mkdir(parents=True)\n"
            "(p / 'try-omarchy-import.pyz').write_bytes(b'fixture')\n"
        )
        self.log = self.root / "calls.log"
        self.fake("git", '''#!/bin/bash
set -eu
printf 'git\\n' >> "$CALL_LOG"
if [[ $3 == rev-parse ]]; then printf '%s\\n' "$FIXTURE_COMMIT"; fi
if [[ $3 == am ]]; then
  mkdir -p "$2/guest"
  cat > "$2/guest/test" <<'TEST'
#!/bin/bash
printf 'contract\\n' >> "$CALL_LOG"
TEST
  cat > "$2/guest/build-container.sh" <<'BUILD'
#!/bin/bash
printf 'build\\n' >> "$CALL_LOG"
printf '<%s>\\n' "$@" >> "$CALL_LOG"
BUILD
  chmod +x "$2/guest/test" "$2/guest/build-container.sh"
fi
''')
        self.fake("sudo", '''#!/bin/bash
set -eu
if [[ $1 == chown ]]; then exit 0; fi
exec "$@"
''')
        self.env = dict(os.environ, PATH=str(self.root / "bin") + os.pathsep + os.environ["PATH"],
                        CALL_LOG=str(self.log), FIXTURE_COMMIT=COMMIT, RUNNER_TEMP=str(self.root))

    def fake(self, name, source):
        path = self.root / "bin" / name
        path.write_text(source)
        path.chmod(0o755)

    def run_wrapper(self, *args):
        return subprocess.run(["bash", str(self.script), *map(str, args)], env=self.env,
                              text=True, capture_output=True)

    def test_default_and_explicit_amd64_keep_original_build_arguments(self):
        for extra in ((), ("--architecture", "amd64"), ("--architecture", "x86_64")):
            with self.subTest(extra=extra):
                self.log.unlink(missing_ok=True)
                output = self.root / "output"
                result = self.run_wrapper("--output", output, *extra)
                self.assertEqual(result.returncode, 0, result.stderr)
                calls = self.log.read_text()
                self.assertIn("contract\nbuild\n<--output>\n<" + str(output) + ">\n", calls)
                self.assertNotIn("<--spec>", calls)

    def test_aarch64_routes_to_its_spec(self):
        output = self.root / "arm-output"
        result = self.run_wrapper("--architecture", "aarch64", "--output", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.log.read_text()
        self.assertIn("contract\nbuild\n<--spec>\n", calls)
        self.assertIn("/guest/spec-aarch64.json>\n<--output>\n<" + str(output) + ">\n", calls)

    def test_contract_only_and_source_only_do_not_build(self):
        contract = self.run_wrapper("--architecture", "aarch64", "--contract-only")
        self.assertEqual(contract.returncode, 0, contract.stderr)
        self.assertIn("contract\n", self.log.read_text())
        self.assertNotIn("build\n", self.log.read_text())
        self.log.unlink()
        output = self.root / "exported-source"
        source = self.run_wrapper("--architecture", "aarch64", "--source-only", "--output", output)
        self.assertEqual(source.returncode, 0, source.stderr)
        self.assertTrue((output / "guest/build-container.sh").is_file())
        self.assertNotIn("contract\n", self.log.read_text())
        self.assertNotIn("build\n", self.log.read_text())

    def test_arm_refuses_existing_output_before_checkout(self):
        for kind in ("visible", "hidden", "file", "symlink"):
            with self.subTest(kind=kind):
                output = self.root / kind
                if kind in ("visible", "hidden"):
                    output.mkdir()
                    (output / ("asset" if kind == "visible" else ".asset")).write_text("keep")
                elif kind == "file":
                    output.write_text("keep")
                else:
                    output.symlink_to(self.root / "missing")
                result = self.run_wrapper("--architecture", "aarch64", "--output", output)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("new or empty", result.stderr)
                self.assertFalse(self.log.exists())

    def test_amd64_refuses_arm_metadata_before_checkout(self):
        for filename, section in (("build-spec.json", "image"), ("guest-manifest.json", "guest")):
            with self.subTest(filename=filename):
                output = self.root / filename
                output.mkdir()
                (output / filename).write_text(json.dumps({section: {"architecture": "aarch64"}}))
                result = self.run_wrapper("--output", output)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("refusing to overwrite", result.stderr)
                self.assertFalse(self.log.exists())

    def test_amd64_allows_own_metadata_and_rejects_invalid_metadata(self):
        output = self.root / "rerun"
        output.mkdir()
        metadata = output / "build-spec.json"
        metadata.write_text(json.dumps({"image": {"architecture": "x86_64"}}))
        self.assertEqual(self.run_wrapper("--output", output).returncode, 0)
        self.log.unlink()
        metadata.write_text("invalid")
        result = self.run_wrapper("--output", output)
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot identify", result.stderr)
        self.assertFalse(self.log.exists())

    def test_amd64_refuses_unidentified_partial_guest_before_work(self):
        for filename in ("rootfs.ext4", "rootfs.ext4.zst", "vmlinuz-linux", "initramfs-linux.img", "SHA256SUMS"):
            with self.subTest(filename=filename):
                output = self.root / filename
                output.mkdir()
                (output / filename).write_text("partial")
                result = self.run_wrapper("--output", output)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("cannot identify existing guest", result.stderr)
                self.assertFalse(self.log.exists())

    def test_invalid_architecture_fails_before_any_git(self):
        for args in (("--architecture", "arm64"), ("--architecture", "bogus"), ("--architecture",)):
            with self.subTest(args=args):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(*args, "--contract-only")
                self.assertEqual(result.returncode, 2)
                self.assertFalse(self.log.exists())
        result = self.run_wrapper("--architecture")
        self.assertEqual(result.returncode, 2)
        self.assertIn("requires a value", result.stderr)
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
