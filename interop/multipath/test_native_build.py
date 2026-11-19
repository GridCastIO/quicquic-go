import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location("native_build", Path(__file__).with_name("native_build.py"))
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


class NativeBuildTests(unittest.TestCase):
    def test_missing_tools_fail_before_any_build_step(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "cmake.*pkg-config.*libcrypto.a"):
                build.check_tools(root / "cmake", root / "pkg-config", root)
            for relative in ("include/openssl/ssl.h", "lib/libcrypto.a", "lib/libssl.a", "bin/openssl"):
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                (root / relative).write_text("")
            with self.assertRaisesRegex(ValueError, "pkg-config"):
                build.check_tools(Path(sys.executable), root / "pkg-config", root)
            build.check_tools(Path(sys.executable), Path(sys.executable), root, which=lambda name: f"/usr/bin/{name}")
            with self.assertRaisesRegex(ValueError, "otool"):
                build.check_tools(Path(sys.executable), Path(sys.executable), root,
                                  which=lambda name: None if name == "otool" else f"/usr/bin/{name}")

    def test_peer_binaries_must_not_load_openssl_dynamically(self):
        build.check_static("qgf-r17-peer:\n\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n")
        with self.assertRaisesRegex(ValueError, "dynamically"):
            build.check_static("picoquicdemo:\n\t/opt/homebrew/opt/openssl@3/lib/libcrypto.3.dylib\n")

    def test_peer_binaries_must_be_exactly_arm64(self):
        build.check_arch("arm64\n")
        for output in ("x86_64\n", "x86_64 arm64\n", ""):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, "not exactly arm64"):
                build.check_arch(output)

    def test_every_compile_uses_the_recorded_sdk(self):
        sdk = "/Library/Developer/CommandLineTools/SDKs/MacOSX27.2.sdk"
        other = "/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk"
        entries = [{"command": f"/usr/bin/cc -isysroot {sdk} -c '/work dir/r17-peer.c'"},
                   {"arguments": ["/usr/bin/cc", "-isysroot", sdk, "-c", "picoquic/sender.c"]}]
        build.check_sysroot(entries, sdk)
        for bad in (entries + [{"command": f"/usr/bin/cc -isysroot {other} -c x.c"}], entries + [{"command": "/usr/bin/cc -c x.c"}], []):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "recorded SDK"):
                build.check_sysroot(bad, sdk)

    def test_self_test_requires_truncation_and_one_pass(self):
        passing = "bound socket 0 127.0.0.1:5000\nself-test datagram 2048 bytes received 1536 truncated 1\nself-test pass\n"
        build.check_self_test(passing)
        for output in ("self-test pass\n", passing.replace("self-test pass\n", ""), passing + "self-test pass\n"):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, "self-test"):
                build.check_self_test(output)

    def test_step_timeout_kills_and_joins_the_process_group(self):
        import fcntl
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            # The grandchild stands in for a make or compiler worker and alone holds an exclusive lock.
            lock, ready, child_pid = directory / "lock", directory / "ready", directory / "child-pid"
            grandchild = ("import fcntl, time; f = open(%r, 'w'); fcntl.flock(f, fcntl.LOCK_EX); "
                          "open(%r, 'w').close(); time.sleep(60)") % (str(lock), str(ready))
            child = ("import os, pathlib, subprocess, sys, time; pathlib.Path(%r).write_text(str(os.getpid())); "
                     "subprocess.Popen([sys.executable, '-c', %r]); "
                     "[time.sleep(0.05) for _ in iter(lambda: not pathlib.Path(%r).exists(), False)]; time.sleep(60)"
                     ) % (str(child_pid), grandchild, str(ready))
            with (directory / "build.log").open("w") as log:
                with self.assertRaises(subprocess.TimeoutExpired):
                    build.run_step([sys.executable, "-c", child], log, directory, timeout=2)
                self.assertTrue(ready.exists(), "the worker was running before the timeout")
                # The direct child was joined, so its PID no longer exists.
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(child_pid.read_text()), 0)
                deadline = time.monotonic() + 10
                with lock.open("w") as handle:
                    while True:
                        try:
                            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            break
                        except BlockingIOError:
                            self.assertLess(time.monotonic(), deadline, "the timed-out step's worker still holds its lock")
                            time.sleep(0.05)
                with self.assertRaises(subprocess.CalledProcessError) as failed:
                    build.run_step([sys.executable, "-c", "import sys; sys.exit(3)"], log, directory)
                self.assertEqual(failed.exception.returncode, 3)
                self.assertEqual(build.run_step([sys.executable, "-c", "print('built')"], log, directory), 0)
            lines = (directory / "build.log").read_text().splitlines()
            self.assertEqual(lines[0], f"$ {sys.executable} -c {child}")
            self.assertEqual(lines[-2:], [f"$ {sys.executable} -c print('built')", "built"])


if __name__ == "__main__":
    unittest.main()
