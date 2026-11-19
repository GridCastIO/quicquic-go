import importlib.util
from pathlib import Path
import sys
import tempfile
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
            build.check_tools(Path(sys.executable), Path(sys.executable), root)

    def test_peer_binaries_must_not_load_openssl_dynamically(self):
        build.check_static("qgf-r17-peer:\n\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n")
        with self.assertRaisesRegex(ValueError, "dynamically"):
            build.check_static("picoquicdemo:\n\t/opt/homebrew/opt/openssl@3/lib/libcrypto.3.dylib\n")

    def test_self_test_requires_truncation_and_one_pass(self):
        passing = "bound socket 0 127.0.0.1:5000\nself-test datagram 2048 bytes received 1536 truncated 1\nself-test pass\n"
        build.check_self_test(passing)
        for output in ("self-test pass\n", passing.replace("self-test pass\n", ""), passing + "self-test pass\n"):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, "self-test"):
                build.check_self_test(output)


if __name__ == "__main__":
    unittest.main()
