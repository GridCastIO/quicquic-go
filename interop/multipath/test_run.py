import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest


sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location("peer_run", Path(__file__).with_name("run.py"))
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class AccountingTests(unittest.TestCase):
    def events(self, cases, action="pass"):
        return [json.dumps({"Action": action, "Package": runner.PACKAGE, "Test": case}) for case in cases]

    def test_both_roles_are_required(self):
        runner.check_cases(self.events(runner.EXPECTED))
        with self.assertRaisesRegex(ValueError, "missing"):
            runner.check_cases(self.events(runner.EXPECTED[:1]))

    def test_skipped_expected_case_fails(self):
        with self.assertRaisesRegex(ValueError, "skip"):
            runner.check_cases(self.events(runner.EXPECTED, "skip"))

    def test_no_tests_and_duplicate_passes_fail(self):
        for events in ([], self.events(runner.EXPECTED + runner.EXPECTED)):
            with self.subTest(events=events), self.assertRaises(ValueError):
                runner.check_cases(events)

    def test_unrelated_package_cannot_supply_evidence(self):
        events = [json.dumps({"Action": "pass", "Package": "other", "Test": case}) for case in runner.EXPECTED]
        with self.assertRaisesRegex(ValueError, "missing"):
            runner.check_cases(events)

    def test_missing_prerequisite_fails_before_execution(self):
        with self.assertRaisesRegex(ValueError, "binary"):
            runner.check_prerequisites("/nonexistent/r1-peer", "linux", "x86_64")
        with self.assertRaisesRegex(ValueError, "Linux amd64"):
            runner.check_prerequisites(__file__, "darwin", "arm64")

    def test_matrix_requires_all_eight_scenarios_in_both_roles(self):
        scenarios = (
            "useful-transfer", "absent-negotiation", "path-zero-ack",
            "key-update-silent-path", "status-backup-failover",
            "abandon-reopen-late-feedback", "same-id-migration-rebinding",
            "unequal-mtu-invalid-frame",
        )
        required = [f"TestPicoquicMultipathMatrix/{scenario}/{role}"
                    for scenario in scenarios for role in ("client", "server")]
        self.assertEqual(runner.MATRIX_EXPECTED, required)
        events = [json.dumps({"Action": "pass", "Package": runner.SMOKE_PACKAGE, "Test": case})
                  for case in required]
        runner.check_cases(events, runner.SMOKE_PACKAGE, runner.MATRIX_EXPECTED)
        for missing in (events[:1], events[:-1], events + events[:1]):
            with self.subTest(events=missing), self.assertRaisesRegex(ValueError, "missing or duplicate"):
                runner.check_cases(missing, runner.SMOKE_PACKAGE, runner.MATRIX_EXPECTED)
        with self.assertRaisesRegex(ValueError, "skip"):
            runner.check_cases(events + [json.dumps({"Action": "skip", "Package": runner.SMOKE_PACKAGE,
                                                  "Test": required[0]})],
                               runner.SMOKE_PACKAGE, runner.MATRIX_EXPECTED)

    def test_matrix_invocation_runs_one_exact_role_with_the_existing_timeout(self):
        command, expected = runner.matrix_invocation("path-zero-ack", "server")
        self.assertEqual(expected, ["TestPicoquicMultipathMatrix/path-zero-ack/server"])
        self.assertIn("-run=^TestPicoquicMultipathMatrix$/^path-zero-ack$/^server$", command)
        self.assertIn("-timeout=90s", command)
        for scenario, role in (("unknown", "server"), ("path-zero-ack", "other")):
            with self.subTest(scenario=scenario, role=role), self.assertRaises(ValueError):
                runner.matrix_invocation(scenario, role)

    def test_bbr_fixed_inventory_and_controller_identity(self):
        scenarios = ("useful-transfer", "abandon-reopen-late-feedback", "same-id-migration-rebinding")
        expected = [f"TestPicoquicMultipathMatrix/{scenario}/{role}"
                    for scenario in scenarios for role in ("client", "server")]
        self.assertEqual(runner.matrix_expected("bbrv3"), expected)
        self.assertEqual(runner.matrix_expected("reno"), runner.MATRIX_EXPECTED)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for case in expected:
                _, scenario, role = case.split("/")
                directory = root / scenario / role
                directory.mkdir(parents=True)
                (directory / "go-test.jsonl").write_text(json.dumps({"Action": "pass", "Package": runner.SMOKE_PACKAGE, "Test": case}) + "\n")
                (directory / "result.json").write_text(json.dumps({"status": "pass", "executed": [case], "controller": "bbrv3", "identity": {"candidate": "a" * 40}}))
            self.assertEqual(runner.check_matrix(root, "bbrv3")["executed"], expected)
            receipt = root / scenarios[0] / "client" / "result.json"
            data = json.loads(receipt.read_text())
            data["controller"] = "reno"
            receipt.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "controller"):
                runner.check_matrix(root, "bbrv3")
        with self.assertRaises(ValueError):
            runner.matrix_invocation("path-zero-ack", "client", controller="bbrv3")

    def test_aggregate_policy_requires_matching_case_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for case in runner.matrix_expected("bbrv3"):
                _, scenario, role = case.split("/")
                directory = root / scenario / role
                directory.mkdir(parents=True)
                (directory / "go-test.jsonl").write_text(json.dumps({"Action": "pass", "Package": runner.SMOKE_PACKAGE, "Test": case}) + "\n")
                (directory / "result.json").write_text(json.dumps({"status": "pass", "executed": [case], "controller": "bbrv3", "policy": "aggregate", "identity": {"candidate": "a" * 40}}))
            self.assertEqual(runner.check_matrix(root, "bbrv3", "aggregate")["policy"], "aggregate")
            with self.assertRaisesRegex(ValueError, "policy"):
                runner.check_matrix(root, "bbrv3", "primary-backup")

    def test_aggregate_requires_case_logs_and_one_candidate_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for case in runner.MATRIX_EXPECTED:
                _, scenario, role = case.split("/")
                directory = root / scenario / role
                directory.mkdir(parents=True)
                (directory / "go-test.jsonl").write_text(json.dumps({"Action": "pass", "Package": runner.SMOKE_PACKAGE, "Test": case}) + "\n")
                (directory / "result.json").write_text(json.dumps({"status": "pass", "executed": [case], "identity": {"candidate": "a" * 40}}))
            with self.assertRaisesRegex(ValueError, "zero"):
                runner.check_matrix(root)
            zero = root / "negotiated-zero"
            zero.mkdir()
            (zero / "go-test.jsonl").write_text("\n".join(json.dumps({"Action": "pass", "Package": runner.SMOKE_PACKAGE, "Test": case}) for case in runner.ZERO_EXPECTED))
            (zero / "result.json").write_text(json.dumps({"status": "pass", "executed": runner.ZERO_EXPECTED, "identity": {"candidate": "a" * 40}}))
            self.assertEqual(runner.check_matrix(root)["executed"], runner.MATRIX_EXPECTED)
            case = root / "path-zero-ack" / "server"
            (case / "result.json").write_text(json.dumps({"status": "pass", "executed": ["TestPicoquicMultipathMatrix/path-zero-ack/server"], "identity": {"candidate": "b" * 40}}))
            with self.assertRaisesRegex(ValueError, "identity"):
                runner.check_matrix(root)
            (case / "go-test.jsonl").unlink()
            with self.assertRaisesRegex(ValueError, "missing"):
                runner.check_matrix(root)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


GO_BUILD_INFO = """peer-matrix.test: go1.27.4
\tpath\tgithub.com/GridCastIO/quicquic-go.test
\tbuild\t-tags=picoquic
\tbuild\tGOARCH=arm64
\tbuild\tGOOS=darwin
"""


class NativeProfileTests(unittest.TestCase):
    """The darwin-native profile is an explicit execution identity, not a Linux fallback."""

    def build_identity(self, directory, peer):
        record = {
            "version": 1, "profile": "darwin-native",
            "platform": {"system": "Darwin", "machine": "arm64", "release": "27.2.0", "macos": "27.2.1"},
            "picoquic": runner.PICOQUIC_PIN, "picotls": runner.PICOTLS_PIN,
            "toolchain": {"cc": "Apple clang version 21.0.0", "sdk_version": "27.2", "sdk_path": "/sdk",
                          "cmake": "cmake version 3.31.12", "cmake_sha256": "c" * 64,
                          "pkg_config": "3.0.11", "pkg_config_sha256": "a" * 64,
                          "openssl": "OpenSSL 3.5.9", "openssl_root": "/openssl",
                          "openssl_static_sha256": {"libcrypto.a": "d" * 64, "libssl.a": "e" * 64}},
            "peer_driver_sha256": sha256(Path(runner.__file__).with_name("peer.c")),
            "binaries": {"picoquicdemo": {"sha256": sha256(peer)}, "qgf-r17-peer": {"sha256": "f" * 64}},
            "self_test": "pass",
        }
        path = Path(directory) / "build-identity.json"
        path.write_text(json.dumps(record))
        return path, record

    def test_identity_dispatch_selects_exactly_one_profile(self):
        self.assertEqual(runner.execution_profile("Linux", "x86_64"), "linux-docker")
        self.assertEqual(runner.execution_profile("Darwin", "arm64"), "darwin-native")
        for system, machine in (("Darwin", "x86_64"), ("Linux", "arm64"), ("Windows", "AMD64")):
            with self.subTest(system=system, machine=machine), self.assertRaisesRegex(ValueError, "no peer execution profile"):
                runner.execution_profile(system, machine)

    def test_requested_profile_must_match_the_host(self):
        runner.check_prerequisites(sys.executable, "darwin", "arm64", "darwin-native")
        with self.assertRaisesRegex(ValueError, "Darwin arm64"):
            runner.check_prerequisites(__file__, "linux", "x86_64", "darwin-native")
        with self.assertRaisesRegex(ValueError, "Linux amd64"):
            runner.check_prerequisites(__file__, "darwin", "arm64", "linux-docker")
        with self.assertRaisesRegex(ValueError, "binary"):
            runner.check_prerequisites("/nonexistent/peer", "darwin", "arm64", "darwin-native")

    def test_native_profile_launches_without_stdbuf(self):
        self.assertEqual(runner.required_executables("linux-docker"), ("go", "stdbuf"))
        self.assertEqual(runner.required_executables("darwin-native"), ("go",))

    def test_build_identity_must_match_pins_platform_driver_and_binary(self):
        with tempfile.TemporaryDirectory() as temporary:
            path, record = self.build_identity(temporary, __file__)
            self.assertEqual(runner.load_build_identity(path, "Darwin", "arm64", __file__), record)
            with self.assertRaisesRegex(ValueError, "platform"):
                runner.load_build_identity(path, "Darwin", "x86_64", __file__)
            with self.assertRaisesRegex(ValueError, "peer binary"):
                runner.load_build_identity(path, "Darwin", "arm64", Path(runner.__file__).with_name("peer.c"))
            for field, value in (("picoquic", "0" * 40), ("version", 2), ("peer_driver_sha256", "0" * 64),
                                 ("self_test", "skip"), ("unexpected", 1)):
                with self.subTest(field=field):
                    path.write_text(json.dumps(record | {field: value}))
                    with self.assertRaises(ValueError):
                        runner.load_build_identity(path, "Darwin", "arm64", __file__)
            for platform_record in ({"system": "Darwin", "machine": "arm64"},
                                    record["platform"] | {"unexpected": "x"}, record["platform"] | {"macos": ""}):
                with self.subTest(platform=platform_record):
                    path.write_text(json.dumps(record | {"platform": platform_record}))
                    with self.assertRaisesRegex(ValueError, "malformed"):
                        runner.load_build_identity(path, "Darwin", "arm64", __file__)
            missing = dict(record)
            del missing["toolchain"]
            path.write_text(json.dumps(missing))
            with self.assertRaisesRegex(ValueError, "build identity"):
                runner.load_build_identity(path, "Darwin", "arm64", __file__)
            path.write_text("{not json")
            with self.assertRaises(ValueError):
                runner.load_build_identity(path, "Darwin", "arm64", __file__)
            with self.assertRaisesRegex(ValueError, "build identity"):
                runner.load_build_identity(Path(temporary) / "absent.json", "Darwin", "arm64", __file__)

    def test_test_binary_must_be_a_tagged_native_build(self):
        settings = runner.check_test_binary_settings(GO_BUILD_INFO, "darwin", "arm64", "go1.27.4")
        self.assertEqual(settings["GOOS"], "darwin")
        with self.assertRaisesRegex(ValueError, "built by go1.27.4, not go1.26.11"):
            runner.check_test_binary_settings(GO_BUILD_INFO, "darwin", "arm64", "go1.26.11")
        for wrong in (GO_BUILD_INFO.replace("-tags=picoquic", "-tags=other"),
                      GO_BUILD_INFO.replace("GOOS=darwin", "GOOS=linux"),
                      GO_BUILD_INFO.replace("\tbuild\tGOARCH=arm64\n", "")):
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                runner.check_test_binary_settings(wrong, "darwin", "arm64")

    def test_matrix_discovery_lists_exactly_the_matrix(self):
        runner.check_listing(["TestPicoquicMultipathMatrix", ""])
        for lines in ([], ["TestPicoquicMultipathMatrix"] * 2, ["TestPicoquicMultipathMatrix", "TestOther"],
                      ["TestPicoquicMultipathSmoke"]):
            with self.subTest(lines=lines), self.assertRaisesRegex(ValueError, "discovery"):
                runner.check_listing(lines)
        command = runner.discovery_command(Path("/bin/peer-matrix.test"))
        self.assertEqual(command, [str(Path("/bin/peer-matrix.test").resolve()), "-test.list", "^TestPicoquicMultipathMatrix$"])
        # A caller-relative binary launches the hashed file, never a PATH lookup.
        relative = runner.discovery_command(Path("./peer-matrix.test"))[0]
        self.assertEqual(relative, str((Path.cwd() / "peer-matrix.test").resolve()))

    def test_native_ordinary_control_runs_the_compiled_self_binary(self):
        command, package, expected = runner.ordinary_invocation(Path("/bin/peer-control.test"))
        self.assertEqual((package, expected), (runner.PACKAGE, runner.EXPECTED))
        self.assertEqual(command[:7], ["go", "tool", "test2json", "-t", "-p", runner.PACKAGE, str(Path("/bin/peer-control.test").resolve())])
        self.assertIn("-test.run=^TestPicoquicOrdinaryControl$", command)
        self.assertEqual(command[-1], "-version=1")
        relative, _, _ = runner.ordinary_invocation(Path("./peer-control.test"))
        self.assertEqual(relative[6], str((Path.cwd() / "peer-control.test").resolve()))
        linux, _, _ = runner.ordinary_invocation(None)
        self.assertEqual(linux, ["go", "test", "-json", "-tags=picoquic", "-run=^TestPicoquicOrdinaryControl$",
                                 "-count=1", "-timeout=90s", "./integrationtests/self", "-version=1"])

    def test_launch_failure_and_timeout_kill_and_join_the_process_group(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            log = directory / "log"
            with self.assertRaises(OSError):
                runner.run_bounded(["/nonexistent/peer"], os.environ, log, 5)
            # The grandchild alone holds an exclusive lock; the kernel releases it when that
            # process exits, so acquiring it observes descendant termination without a PID race.
            lock, ready, child_pid = directory / "lock", directory / "ready", directory / "child-pid"
            grandchild = ("import fcntl, time; f = open(%r, 'w'); fcntl.flock(f, fcntl.LOCK_EX); "
                          "open(%r, 'w').close(); time.sleep(60)") % (str(lock), str(ready))
            child = ("import os, pathlib, subprocess, sys, time; pathlib.Path(%r).write_text(str(os.getpid())); "
                     "subprocess.Popen([sys.executable, '-c', %r]); "
                     "[time.sleep(0.05) for _ in iter(lambda: not pathlib.Path(%r).exists(), False)]; time.sleep(60)"
                     ) % (str(child_pid), grandchild, str(ready))
            with self.assertRaises(subprocess.TimeoutExpired):
                runner.run_bounded([sys.executable, "-c", child], os.environ, log, 10)
            self.assertTrue(ready.exists(), "the grandchild was running before the timeout")
            # The direct child was joined by run_bounded, so its PID no longer exists.
            with self.assertRaises(ProcessLookupError):
                os.kill(int(child_pid.read_text()), 0)
            import fcntl
            deadline = time.monotonic() + 10
            with lock.open("w") as handle:
                while True:
                    try:
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        self.assertLess(time.monotonic(), deadline, "the killed grandchild still holds its lock")
                        time.sleep(0.05)
            self.assertEqual(runner.run_bounded([sys.executable, "-c", "print('ok')"], os.environ, log, 5), 0)
            self.assertEqual(log.read_text().strip(), "ok")

    def native_root(self, temporary):
        root = Path(temporary)
        core = {"candidate": "a" * 40, "tree": "b" * 40, "go": "go version go1.27.4 darwin/arm64",
                "build_identity_sha256": "c" * 64,
                "kernel": {"system": "Darwin", "release": "27.2.0", "version": "Darwin Kernel Version 27.2.0", "machine": "arm64"},
                "runner_sha256": "1" * 64, "peer_driver_sha256": "2" * 64, "test_binary_sha256": "3" * 64}
        run = {"command": ["go"], "started": "2026-11-19T00:00:00+00:00", "duration_seconds": 1.0}
        control = root / "ordinary-control"
        control.mkdir()
        (control / "go-test.jsonl").write_text("\n".join(
            json.dumps({"Action": "pass", "Package": runner.PACKAGE, "Test": case}) for case in runner.EXPECTED))
        (control / "result.json").write_text(json.dumps(run | {
            "profile": "darwin-native", "mode": "ordinary-control", "policy": "primary-backup", "controller": "reno",
            "status": "pass", "executed": runner.EXPECTED, "identity": core | {"peer_binary_sha256": "d" * 64}}))
        discovery = root / "matrix-discovery"
        discovery.mkdir()
        (discovery / "list.txt").write_text("TestPicoquicMultipathMatrix\n")
        (discovery / "result.json").write_text(json.dumps(run | {
            "profile": "darwin-native", "mode": "matrix-discovery", "status": "pass",
            "listed": runner.DISCOVERY_EXPECTED, "executed": [], "identity": core | {"test_binary_sha256": "4" * 64}}))
        return root

    def test_native_receipts_require_both_roles_and_discovery_separately(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.native_root(temporary)
            result = runner.check_native(root)
            self.assertEqual(result["ordinary_control"]["executed"], runner.EXPECTED)
            self.assertEqual(result["matrix_discovery"]["listed"], runner.DISCOVERY_EXPECTED)
            self.assertEqual(result["matrix_discovery"]["executed"], [])
            discovery = json.loads((root / "matrix-discovery" / "result.json").read_text())
            (root / "matrix-discovery" / "result.json").write_text(json.dumps(discovery | {"identity": discovery["identity"] | {"candidate": "e" * 40}}))
            with self.assertRaisesRegex(ValueError, "identity"):
                runner.check_native(root)
            (root / "matrix-discovery" / "result.json").write_text(json.dumps(discovery | {"executed": runner.MATRIX_EXPECTED}))
            with self.assertRaisesRegex(ValueError, "discovery"):
                runner.check_native(root)
            identity = discovery["identity"]
            linux_kernel = identity["kernel"] | {"system": "Linux", "machine": "x86_64"}
            for malformed in (discovery | {"unexpected": 1}, discovery | {"identity": identity | {"unexpected": 1}}, ["list"],
                              discovery | {"identity": identity | {"kernel": linux_kernel}},
                              discovery | {"identity": identity | {"test_binary_sha256": None}},
                              discovery | {"identity": identity | {"go": "go version go1.27.4 linux/amd64"}},
                              discovery | {"duration_seconds": True}, discovery | {"status": "skip"}):
                with self.subTest(malformed=malformed):
                    (root / "matrix-discovery" / "result.json").write_text(json.dumps(malformed))
                    with self.assertRaisesRegex(ValueError, "malformed"):
                        runner.check_native(root)
            control = json.loads((root / "ordinary-control" / "result.json").read_text())
            for receipt, data in (("ordinary-control", control), ("matrix-discovery", discovery)):
                (root / receipt / "result.json").write_text(json.dumps(data | {"identity": data["identity"] | {"candidate": "x", "tree": 1}}))
            with self.assertRaisesRegex(ValueError, "malformed"):
                runner.check_native(root)
            for receipt, data in (("ordinary-control", control), ("matrix-discovery", discovery)):
                (root / receipt / "result.json").write_text(json.dumps(data | {"identity": data["identity"] | {"go": "go version go darwin/arm64"}}))
            with self.assertRaisesRegex(ValueError, "malformed"):
                runner.check_native(root)
            (root / "matrix-discovery" / "result.json").unlink()
            with self.assertRaisesRegex(ValueError, "missing"):
                runner.check_native(root)
        with tempfile.TemporaryDirectory() as temporary:
            root = self.native_root(temporary)
            (root / "ordinary-control" / "go-test.jsonl").write_text(json.dumps({"Action": "skip", "Package": runner.PACKAGE, "Test": runner.EXPECTED[0]}))
            with self.assertRaisesRegex(ValueError, "skip"):
                runner.check_native(root)

    def test_docker_and_runner_pins_agree(self):
        dockerfile = Path(runner.__file__).with_name("Dockerfile").read_text()
        self.assertEqual(re.findall(r"fetch -q --depth 1 origin ([0-9a-f]{40})", dockerfile), [runner.PICOQUIC_PIN])
        self.assertEqual(re.findall(r"PICOQUIC_FETCH_PTLS_TAG=([0-9a-f]{40})", dockerfile), [runner.PICOTLS_PIN])


if __name__ == "__main__":
    unittest.main()
