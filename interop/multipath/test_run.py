import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location("peer_run", Path(__file__).with_name("run.py"))
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
import test_candidate_binding as binding_fixture


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

    def test_numbered_repeat_of_a_role_is_a_duplicate(self):
        # Go renames a second "client" subtest "client#01"; parent and package events stay ordinary.
        normal = self.events(runner.EXPECTED + ["TestPicoquicOrdinaryControl"]) + [json.dumps({"Action": "pass", "Package": runner.PACKAGE})]
        runner.check_cases(normal)
        with self.assertRaisesRegex(ValueError, "duplicate expected case"):
            runner.check_cases(normal + self.events([runner.EXPECTED[0] + "#01"]))

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
            # A child that exits nonzero while a descendant survives keeps its status and still loses the descendant.
            ready.unlink()
            crashing = ("import pathlib, subprocess, sys, time; subprocess.Popen([sys.executable, '-c', %r]); "
                        "[time.sleep(0.05) for _ in iter(lambda: not pathlib.Path(%r).exists(), False)]; sys.exit(2)"
                        ) % (grandchild, str(ready))
            self.assertEqual(runner.run_bounded([sys.executable, "-c", crashing], os.environ, log, 10), 2)
            self.assertTrue(ready.exists(), "the grandchild was running when its parent exited")
            deadline = time.monotonic() + 10
            with lock.open("w") as handle:
                while True:
                    try:
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        self.assertLess(time.monotonic(), deadline, "the orphaned grandchild still holds its lock")
                        time.sleep(0.05)
            self.assertEqual(runner.run_bounded([sys.executable, "-c", "print('ok')"], os.environ, log, 5), 0)
            self.assertEqual(log.read_text().strip(), "ok")

    def test_sigterm_kills_and_joins_the_process_group(self):
        import fcntl
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            lock, ready, child_pid = directory / "lock", directory / "ready", directory / "child-pid"
            grandchild = ("import fcntl, time; f = open(%r, 'w'); fcntl.flock(f, fcntl.LOCK_EX); "
                          "open(%r, 'w').close(); time.sleep(60)") % (str(lock), str(ready))
            child = ("import os, pathlib, subprocess, sys, time; pathlib.Path(%r).write_text(str(os.getpid())); "
                     "subprocess.Popen([sys.executable, '-c', %r]); "
                     "[time.sleep(0.05) for _ in iter(lambda: not pathlib.Path(%r).exists(), False)]; time.sleep(60)"
                     ) % (str(child_pid), grandchild, str(ready))
            # A separate supervising process, so the test can deliver SIGTERM to the runner alone. It starts
            # from the default disposition: the runner deliberately keeps an inherited ignore. Like a script
            # run, it puts the runner's directory first on sys.path for the runner's sibling imports.
            supervisor = ("import importlib.util, os, signal, sys; sys.dont_write_bytecode = True; "
                          "sys.path.insert(0, %r); signal.signal(signal.SIGTERM, signal.SIG_DFL); "
                          "spec = importlib.util.spec_from_file_location('peer_run', %r); "
                          "runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner); "
                          "print('returned', runner.run_bounded([sys.executable, '-c', %r], os.environ, %r, 30))"
                          ) % (str(Path(runner.__file__).resolve().parent), str(Path(runner.__file__).resolve()), child,
                               str(directory / "log"))
            process = subprocess.Popen([sys.executable, "-B", "-c", supervisor],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                deadline = time.monotonic() + 10
                while not ready.exists():
                    self.assertIsNone(process.poll(), "the supervisor exited before SIGTERM")
                    self.assertLess(time.monotonic(), deadline, "the grandchild never took its lock")
                    time.sleep(0.05)
                process.send_signal(signal.SIGTERM)
                stdout, stderr = process.communicate(timeout=10)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
            # The runner fails through the interrupt path rather than returning a status.
            self.assertNotEqual(process.returncode, 0)
            self.assertIn("KeyboardInterrupt: SIGTERM", stderr)
            self.assertNotIn("returned", stdout)
            with self.assertRaises(ProcessLookupError):
                os.kill(int(child_pid.read_text()), 0)
            deadline = time.monotonic() + 10
            with lock.open("w") as handle:
                while True:
                    try:
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        self.assertLess(time.monotonic(), deadline, "the grandchild outlived its terminated runner")
                        time.sleep(0.05)

    def test_sigterm_conversion_restores_the_caller_disposition(self):
        self.addCleanup(signal.signal, signal.SIGTERM, signal.getsignal(signal.SIGTERM))
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "log"
            show = [sys.executable, "-c", "import signal; print(signal.getsignal(signal.SIGTERM).name)"]
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            self.assertEqual(runner.run_bounded(show, os.environ, log, 5), 0)
            self.assertEqual(log.read_text().strip(), "SIG_DFL")
            self.assertIs(signal.getsignal(signal.SIGTERM), signal.SIG_DFL)
            with self.assertRaises(subprocess.TimeoutExpired):
                runner.run_bounded([sys.executable, "-c", "import time; time.sleep(60)"], os.environ, log, 0.5)
            self.assertIs(signal.getsignal(signal.SIGTERM), signal.SIG_DFL)
            # An inherited ignore stays installed for the runner and its children.
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            self.assertEqual(runner.run_bounded(show, os.environ, log, 5), 0)
            self.assertEqual(log.read_text().strip(), "SIG_IGN")
            self.assertIs(signal.getsignal(signal.SIGTERM), signal.SIG_IGN)

    @staticmethod
    def binding(digest, package):
        return {"method": "rebuild-from-candidate/v1", "package": package, "form": "test", "toolchain": "go1.27.4",
                "settings": {"-tags": "picoquic", "GOOS": "darwin", "GOARCH": "arm64"}, "sha256": digest,
                "rebuild": "byte-identical"}

    def test_native_receipts_read_the_binding_through_its_owner(self):
        # #1576: one binding schema, candidate_binding's, for this runner and the verdicts.
        owner = binding_fixture.binding
        self.assertIs(runner.BINDING_SCHEMA["source"], owner.SOURCE_SCHEMA)
        self.assertIs(runner.BINDING_SCHEMA["test_binary_binding"], owner.BINDING_SCHEMA)
        self.assertIs(runner.NATIVE_IDENTITY_SCHEMA["test_binary_binding"], owner.BINDING_SCHEMA)

    def test_native_receipts_require_their_candidate_binding(self):
        for receipt in ("ordinary-control", "matrix-discovery"):
            for change, message in (
                    (lambda identity: identity.pop("test_binary_binding"), "lacks the #1528 candidate binding"),
                    (lambda identity: identity.pop("source"), "lacks the #1528 candidate binding"),
                    (lambda identity: identity["source"].update(commit="e" * 40), "source commit"),
                    (lambda identity: identity["source"].update(tree="e" * 40), "source tree"),
                    (lambda identity: identity["test_binary_binding"].update(sha256="e" * 64), "binding names"),
                    (lambda identity: identity["source"].update(clean=False), "malformed")):
                with self.subTest(receipt=receipt, message=message), tempfile.TemporaryDirectory() as temporary:
                    root = self.native_root(temporary)
                    path = root / receipt / "result.json"
                    data = json.loads(path.read_text())
                    change(data["identity"])
                    path.write_text(json.dumps(data))
                    with self.assertRaisesRegex(ValueError, message):
                        runner.check_native(root)

    def native_root(self, temporary):
        root = Path(temporary)
        core = {"candidate": "a" * 40, "tree": "b" * 40, "go": "go version go1.27.4 darwin/arm64",
                "build_identity_sha256": "c" * 64,
                "kernel": {"system": "Darwin", "release": "27.2.0", "version": "Darwin Kernel Version 27.2.0", "machine": "arm64"},
                "runner_sha256": "1" * 64, "peer_driver_sha256": "2" * 64, "test_binary_sha256": "3" * 64,
                "source": {"commit": "a" * 40, "tree": "b" * 40, "head_tree": "b" * 40, "clean": True},
                "test_binary_binding": self.binding("3" * 64, "github.com/GridCastIO/quicquic-go/integrationtests/self")}
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
            "listed": runner.DISCOVERY_EXPECTED, "executed": [],
            "identity": core | {"test_binary_sha256": "4" * 64,
                                "test_binary_binding": self.binding("4" * 64, "github.com/GridCastIO/quicquic-go")}}))
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
            # Each shared digest alone must agree; the two test binaries differ by design.
            (root / "ordinary-control" / "result.json").write_text(json.dumps(control))
            for key in ("runner_sha256", "peer_driver_sha256"):
                with self.subTest(key=key):
                    (root / "matrix-discovery" / "result.json").write_text(json.dumps(discovery | {"identity": identity | {key: "9" * 64}}))
                    with self.assertRaisesRegex(ValueError, "do not share"):
                        runner.check_native(root)
            (root / "matrix-discovery" / "result.json").write_text(json.dumps(discovery))
            runner.check_native(root)
            jsonl = root / "ordinary-control" / "go-test.jsonl"
            jsonl.write_text(jsonl.read_text() + "\n" + json.dumps({"Action": "pass", "Package": runner.PACKAGE, "Test": runner.EXPECTED[0] + "#01"}))
            with self.assertRaisesRegex(ValueError, "duplicate expected case"):
                runner.check_native(root)
            (root / "matrix-discovery" / "result.json").unlink()
            with self.assertRaisesRegex(ValueError, "missing"):
                runner.check_native(root)
        with tempfile.TemporaryDirectory() as temporary:
            root = self.native_root(temporary)
            (root / "ordinary-control" / "go-test.jsonl").write_text(json.dumps({"Action": "skip", "Package": runner.PACKAGE, "Test": runner.EXPECTED[0]}))
            with self.assertRaisesRegex(ValueError, "skip"):
                runner.check_native(root)

    def case_identity(self):
        """A darwin-native identity for the matrix test binary and the recorded peer."""
        return {"candidate": "a" * 40, "tree": "b" * 40, "go": "go version go1.27.4 darwin/arm64",
                "build_identity_sha256": "c" * 64,
                "kernel": {"system": "Darwin", "release": "27.2.0", "version": "Darwin Kernel Version 27.2.0", "machine": "arm64"},
                "runner_sha256": "1" * 64, "peer_driver_sha256": "2" * 64, "test_binary_sha256": "4" * 64,
                "source": {"commit": "a" * 40, "tree": "b" * 40, "head_tree": "b" * 40, "clean": True},
                "test_binary_binding": self.binding("4" * 64, "github.com/GridCastIO/quicquic-go"),
                "peer_binary_sha256": "d" * 64}

    def test_build_identity_names_the_peer_each_mode_launches(self):
        # The matrix and negotiated-zero receipts carry qgf-r17-peer; the ordinary control, picoquicdemo.
        with tempfile.TemporaryDirectory() as temporary:
            path, record = self.build_identity(temporary, __file__)
            self.assertEqual(runner.load_build_identity(path, "Darwin", "arm64", __file__, "picoquicdemo"), record)
            with self.assertRaisesRegex(ValueError, "not the qgf-r17-peer"):
                runner.load_build_identity(path, "Darwin", "arm64", __file__, "qgf-r17-peer")
        self.assertEqual(runner.NATIVE_PEERS, {"ordinary-control": "picoquicdemo", "matrix-discovery": None,
                                               "matrix": "qgf-r17-peer", "negotiated-zero": "qgf-r17-peer"})
        for argv, peer in ((["--matrix", "--scenario", "useful-transfer", "--role", "client"], "qgf-r17-peer"),
                           (["--zero-vectors"], "qgf-r17-peer"), ([], "picoquicdemo")):
            with self.subTest(argv=argv), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.native_case(root, *argv, "--output", str(root / "out"))
                self.assertEqual(self.native_identity_mock.call_args.kwargs.get("peer"), peer)

    def test_default_validator_refuses_native_receipts(self):
        # Without --profile darwin-native, a native root fails before matrix-result.json exists.
        for controller, policy in (("reno", "primary-backup"), ("bbrv3", "aggregate")):
            with self.subTest(controller=controller), tempfile.TemporaryDirectory() as temporary:
                root = self.native_matrix_root(Path(temporary), controller, policy)
                for directory in [*root.glob("*/*"), root / "negotiated-zero"]:
                    receipt = directory / "result.json"
                    if receipt.is_file():
                        data = json.loads(receipt.read_text())
                        data["identity"] = {k: v for k, v in data["identity"].items() if k not in ("source", "test_binary_binding")}
                        receipt.write_text(json.dumps(data))
                argv = ["run.py", "--validate-matrix", "--controller", controller, "--policy", policy, "--output", str(root)]
                with mock.patch.object(sys, "argv", argv), self.assertRaisesRegex(ValueError, "--profile darwin-native"):
                    runner.main()
                self.assertFalse((root / "matrix-result.json").exists())

    def run_native(self, argv, identity=None, status=0):
        """main() under darwin-native with the host, toolchain and #1528 binding stubbed:
        native_identity returns identity, and each launch passes the cases its command selects."""
        launches = []

        def run_bounded(command, env, log_path, timeout):
            launches.append((command, env, timeout))
            selected = next(argument for argument in command if argument.startswith("-test.run="))
            if "TestPicoquicMultipathMatrix" in selected:
                scenario, role = re.fullmatch(r"-test\.run=\^TestPicoquicMultipathMatrix\$/\^(.+)\$/\^(.+)\$", selected).groups()
                cases, package = [f"TestPicoquicMultipathMatrix/{scenario}/{role}"], runner.SMOKE_PACKAGE
            elif "NegotiatedZero" in selected:
                cases, package = runner.ZERO_EXPECTED, runner.SMOKE_PACKAGE
            else:
                cases, package = runner.EXPECTED, runner.PACKAGE
            Path(log_path).write_text("\n".join(json.dumps({"Action": "pass", "Package": package, "Test": case}) for case in cases))
            return status

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {"QGF_SOURCE_COMMIT": "a" * 40, "QGF_SOURCE_TREE": "b" * 40}))
            stack.enter_context(mock.patch.object(sys, "argv", ["run.py", "--profile", "darwin-native", *argv]))
            stack.enter_context(mock.patch.object(runner.platform, "system", return_value="Darwin"))
            stack.enter_context(mock.patch.object(runner.platform, "machine", return_value="arm64"))
            stack.enter_context(mock.patch.object(runner.shutil, "which", return_value="/usr/bin/stand-in"))
            self.native_identity_mock = stack.enter_context(
                mock.patch.object(runner, "native_identity", return_value=identity or self.case_identity()))
            stack.enter_context(mock.patch.object(runner, "run_bounded", side_effect=run_bounded))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            runner.main()
        return launches

    def native_case(self, root, *mode, identity=None):
        """One native execution with the protocol's binaries; mode selects the case."""
        return self.run_native([*mode, "--binary", sys.executable, "--test-binary", sys.executable,
                                "--build-identity", str(root / "build-identity.json")], identity)

    def test_native_matrix_zero_vectors_and_validation_are_admitted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for case in runner.matrix_expected("reno"):
                _, scenario, role = case.split("/")
                output = root / "reno" / scenario / role
                launches = self.native_case(root, "--matrix", "--scenario", scenario, "--role", role, "--output", str(output))
                command, env, timeout = launches[0]
                self.assertEqual(command, runner.matrix_invocation(scenario, role, Path(sys.executable).resolve())[0])
                self.assertEqual((env["PICOQUIC_CONTROLLER"], env["PICOQUIC_POLICY"], timeout), ("reno", "primary-backup", 120))
                self.assertEqual(env["PICOQUIC_BINARY"], str(Path(sys.executable).resolve()))
                for name in ("attempt.json", "result.json"):
                    receipt = json.loads((output / name).read_text())
                    self.assertEqual((receipt["profile"], receipt["mode"]), ("darwin-native", "matrix"), name)
                    self.assertEqual(receipt["identity"], self.case_identity())
                self.assertEqual(json.loads((output / "result.json").read_text())["executed"], [case])
            zero = root / "reno" / "negotiated-zero"
            command, _, _ = self.native_case(root, "--zero-vectors", "--output", str(zero))[0]
            self.assertEqual(command[:7], ["go", "tool", "test2json", "-t", "-p", runner.SMOKE_PACKAGE, str(Path(sys.executable).resolve())])
            self.assertIn("-test.run=^TestMultipathNegotiatedZero(Vectors|ControlledPeer)$", command)
            receipt = json.loads((zero / "result.json").read_text())
            self.assertEqual((receipt["mode"], receipt["executed"]), ("negotiated-zero", runner.ZERO_EXPECTED))
            self.run_native(["--validate-matrix", "--output", str(root / "reno")])
            result = json.loads((root / "reno" / "matrix-result.json").read_text())
            self.assertEqual((result["profile"], result["status"], result["controller"], result["policy"]),
                             ("darwin-native", "pass", "reno", "primary-backup"))
            self.assertEqual(result["executed"], runner.MATRIX_EXPECTED)
            self.assertEqual(result["identity"], self.case_identity())
            self.assertEqual(result["negotiated_zero"], {"executed": runner.ZERO_EXPECTED, "independent_peer": False})
            # The BBR aggregate root: six cases, no negotiated-zero receipt.
            for case in runner.matrix_expected("bbrv3"):
                _, scenario, role = case.split("/")
                self.native_case(root, "--matrix", "--scenario", scenario, "--role", role, "--controller", "bbrv3",
                                 "--policy", "aggregate", "--output", str(root / "aggregate" / scenario / role))
            self.run_native(["--validate-matrix", "--controller", "bbrv3", "--policy", "aggregate", "--output", str(root / "aggregate")])
            result = json.loads((root / "aggregate" / "matrix-result.json").read_text())
            self.assertEqual((result["profile"], result["controller"], result["policy"]), ("darwin-native", "bbrv3", "aggregate"))
            self.assertNotIn("negotiated_zero", result)
            with self.assertRaisesRegex(ValueError, "policy"):
                self.run_native(["--validate-matrix", "--controller", "bbrv3", "--output", str(root / "aggregate")])

    def test_native_modes_have_distinct_labels(self):
        self.assertEqual(set(runner.NATIVE_RECEIPT_SCHEMAS), {"ordinary-control", "matrix-discovery", "matrix", "negotiated-zero"})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.native_case(root, "--output", str(root / "ordinary-control"),
                             identity=self.case_identity() | {"test_binary_sha256": "3" * 64,
                                                              "test_binary_binding": self.binding("3" * 64, runner.PACKAGE)})
            for name in ("attempt.json", "result.json"):
                self.assertEqual(json.loads((root / "ordinary-control" / name).read_text())["mode"], "ordinary-control")
            matrix = self.native_matrix_root(root / "matrix")
            runner.check_native_matrix(matrix)
            # A receipt read as another mode's evidence is refused by its label.
            for path, label in ((matrix / "path-zero-ack" / "server" / "result.json", "ordinary-control"),
                                (matrix / "path-zero-ack" / "server" / "result.json", "negotiated-zero"),
                                (matrix / "negotiated-zero" / "result.json", "matrix")):
                with self.subTest(path=path, label=label):
                    original = path.read_text()
                    path.write_text(json.dumps(json.loads(original) | {"mode": label}))
                    with self.assertRaisesRegex(ValueError, "malformed .*mode"):
                        runner.check_native_matrix(matrix)
                    path.write_text(original)

    def native_matrix_root(self, root, controller="reno", policy="primary-backup"):
        """Native case receipts as the darwin-native matrix writes them, plus negotiated-zero for Reno."""
        run = {"profile": "darwin-native", "status": "pass", "command": ["go"], "started": "2026-11-19T00:00:00+00:00",
               "duration_seconds": 1.0, "identity": self.case_identity()}
        for case in runner.matrix_expected(controller):
            _, scenario, role = case.split("/")
            directory = root / scenario / role
            directory.mkdir(parents=True)
            (directory / "go-test.jsonl").write_text(json.dumps({"Action": "pass", "Package": runner.SMOKE_PACKAGE, "Test": case}) + "\n")
            (directory / "result.json").write_text(json.dumps(run | {"mode": "matrix", "policy": policy, "controller": controller,
                                                                     "executed": [case]}))
        if controller == "reno":
            zero = root / "negotiated-zero"
            zero.mkdir()
            (zero / "go-test.jsonl").write_text("\n".join(
                json.dumps({"Action": "pass", "Package": runner.SMOKE_PACKAGE, "Test": case}) for case in runner.ZERO_EXPECTED))
            (zero / "result.json").write_text(json.dumps(run | {"mode": "negotiated-zero", "policy": "primary-backup",
                                                                "controller": "reno", "executed": runner.ZERO_EXPECTED}))
        return root

    def test_native_matrix_readback_refuses_foreign_or_unbound_receipts(self):
        case = Path("same-id-migration-rebinding") / "client"
        for path, change, message in (
                (case, lambda identity: identity.update(runner_sha256="9" * 64), "do not share one candidate/toolchain/build identity"),
                (case, lambda identity: identity["kernel"].update(release="27.3.0"), "do not share"),
                (case, lambda identity: identity.update(peer_binary_sha256="9" * 64), "do not share"),
                (case, lambda identity: identity.pop("test_binary_binding"), "lacks the #1528 candidate binding"),
                (case, lambda identity: identity.pop("source"), "lacks the #1528 candidate binding"),
                (case, lambda identity: identity["test_binary_binding"].update(sha256="e" * 64), "binding names"),
                (case, lambda identity: identity["source"].update(commit="e" * 40), "source commit"),
                (case, lambda identity: identity.pop("peer_binary_sha256"), "malformed"),
                (Path("negotiated-zero"), lambda identity: identity.update(test_binary_sha256="9" * 64,
                                                                          test_binary_binding=self.binding("9" * 64, runner.SMOKE_PACKAGE)),
                 "negotiated-zero receipt identity"),
                (Path("negotiated-zero"), lambda identity: identity.pop("test_binary_binding"), "lacks the #1528 candidate binding")):
            with self.subTest(path=str(path), message=message), tempfile.TemporaryDirectory() as temporary:
                root = self.native_matrix_root(Path(temporary))
                receipt = root / path / "result.json"
                data = json.loads(receipt.read_text())
                change(data["identity"])
                receipt.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, message):
                    runner.check_native_matrix(root)
        with tempfile.TemporaryDirectory() as temporary:
            root = self.native_matrix_root(Path(temporary))
            # A Linux-shaped receipt carries no native profile or mode.
            receipt = root / case / "result.json"
            data = json.loads(receipt.read_text())
            receipt.write_text(json.dumps({key: value for key, value in data.items() if key not in ("profile", "mode")}))
            with self.assertRaisesRegex(ValueError, "malformed"):
                runner.check_native_matrix(root)
            receipt.write_text(json.dumps(data | {"executed": ["TestPicoquicMultipathMatrix/path-zero-ack/client"]}))
            with self.assertRaisesRegex(ValueError, "invalid case receipt"):
                runner.check_native_matrix(root)
            receipt.write_text(json.dumps(data | {"controller": "bbrv3"}))
            with self.assertRaisesRegex(ValueError, "controller"):
                runner.check_native_matrix(root)
            receipt.write_text(json.dumps(data))
            (root / "negotiated-zero" / "result.json").unlink()
            with self.assertRaisesRegex(ValueError, "negotiated-zero"):
                runner.check_native_matrix(root)
        with tempfile.TemporaryDirectory() as temporary:
            root = self.native_matrix_root(Path(temporary), "bbrv3", "aggregate")
            self.assertEqual(runner.check_native_matrix(root, "bbrv3", "aggregate")["executed"], runner.matrix_expected("bbrv3"))
            with self.assertRaisesRegex(ValueError, "policy"):
                runner.check_native_matrix(root, "bbrv3", "primary-backup")
            (root / "useful-transfer" / "server" / "go-test.jsonl").unlink()
            with self.assertRaisesRegex(ValueError, "missing"):
                runner.check_native_matrix(root, "bbrv3", "aggregate")

    def test_native_refusals_that_remain(self):
        # The protocol has no native R14 smoke; aggregate stays the fixed BBR matrix; BBR is matrix-only.
        for argv, message in ((["--smoke", "--binary", sys.executable], "R14 smoke"),
                              (["--matrix", "--scenario", "useful-transfer", "--role", "client", "--policy", "aggregate",
                                "--binary", sys.executable], "aggregate requires the fixed BBR matrix"),
                              (["--zero-vectors", "--controller", "bbrv3", "--binary", sys.executable], "BBR is supported only"),
                              (["--zero-vectors", "--policy", "aggregate", "--controller", "bbrv3", "--binary", sys.executable],
                               "aggregate requires the fixed BBR matrix"),
                              (["--matrix", "--scenario", "useful-transfer", "--binary", sys.executable], "--scenario and --role"),
                              (["--zero-vectors"], "--binary is required"),
                              (["--matrix", "--scenario", "useful-transfer", "--role", "client", "--binary", sys.executable],
                               "--test-binary and --build-identity")):
            with self.subTest(argv=argv), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "output"
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
                    self.run_native([*argv, "--output", str(output)])
                self.assertIn(message, stderr.getvalue())
                self.assertFalse(output.exists())

    def test_docker_and_runner_pins_agree(self):
        dockerfile = Path(runner.__file__).with_name("Dockerfile").read_text()
        self.assertEqual(re.findall(r"fetch -q --depth 1 origin ([0-9a-f]{40})", dockerfile), [runner.PICOQUIC_PIN])
        self.assertEqual(re.findall(r"PICOQUIC_FETCH_PTLS_TAG=([0-9a-f]{40})", dockerfile), [runner.PICOTLS_PIN])


class NativeBindingTests(unittest.TestCase):
    """MP-MAC #1528: darwin-native refuses a test binary that is not a byte-identical
    rebuild of the clean QGF_SOURCE_COMMIT/QGF_SOURCE_TREE checkout, before any launch."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.repo = binding_fixture.FixtureRepo(self.root)
        self.identity, _ = NativeProfileTests.build_identity(None, self.root, __file__)

    def build(self, name):
        return self.repo.build(name, tags="picoquic")

    def run_driver(self, test_binary, commit=None, tree=None, profile="darwin-native"):
        """--discover-matrix through main; launching the bound binary is recorded and fails."""
        launches, real_popen, real_output = [], subprocess.Popen, subprocess.check_output

        def popen(command, *args, **kwargs):
            if Path(command[0]).resolve() == Path(test_binary).resolve():
                launches.append(command)
                raise OSError("launch spy: nothing runs in a binding test")
            return real_popen(command, *args, **kwargs)

        def check_output(command, *args, **kwargs):
            # The host's go may target another platform; the fixture was built by this go.
            if command == ["go", "version"]:
                return f"go version {binding_fixture.GO_VERSION} darwin/arm64\n"
            return real_output(command, *args, **kwargs)

        environment = {"QGF_SOURCE_COMMIT": commit or self.repo.head(), "QGF_SOURCE_TREE": tree or self.repo.tree()}
        argv = ["run.py", "--profile", profile, "--discover-matrix", "--test-binary", str(test_binary),
                "--build-identity", str(self.identity), "--source", str(self.repo.root), "--output", str(self.root / "output")]
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, environment))
            stack.enter_context(mock.patch.object(sys, "argv", argv))
            stack.enter_context(mock.patch.object(runner.platform, "system", return_value="Darwin"))
            stack.enter_context(mock.patch.object(runner.platform, "machine", return_value="arm64"))
            stack.enter_context(mock.patch.object(runner.subprocess, "Popen", side_effect=popen))
            stack.enter_context(mock.patch.object(runner.subprocess, "check_output", side_effect=check_output))
            runner.main()
        return launches

    def refused(self, pattern, test_binary, **identity):
        with self.assertRaisesRegex(ValueError, pattern):
            self.run_driver(test_binary, **identity)
        self.assertFalse((self.root / "output").exists(), "refused before any output")

    def test_candidate_build_is_accepted_and_recorded(self):
        test_binary = self.build("peer-matrix.test")
        with self.assertRaisesRegex(OSError, "launch spy"):
            self.run_driver(test_binary)
        identity = json.loads((self.root / "output" / "attempt.json").read_text())["identity"]
        self.assertEqual(identity["source"], {"commit": self.repo.head(), "tree": self.repo.tree(),
                                              "head_tree": self.repo.tree(), "clean": True})
        bound = identity["test_binary_binding"]
        self.assertEqual((bound["sha256"], bound["form"], bound["rebuild"]), (sha256(test_binary), "test", "byte-identical"))
        self.assertEqual(bound["settings"]["-tags"], "picoquic")
        runner.check_record(identity, runner.NATIVE_IDENTITY_SCHEMA, "native identity")

    def test_stale_dirty_mismatched_or_ignored_builds_are_refused(self):
        first, first_tree = self.repo.head(), self.repo.tree()
        stale = self.repo.stale("stale.test", tags="picoquic")
        current = self.build("current.test")
        self.refused("is not the candidate's build", stale)
        self.refused("not the candidate", current, commit=first)
        self.refused("not the recorded tree", current, tree=first_tree)
        self.repo.write("extra_ignored.go", "package bindingfixture\n\nconst Extra = 1\n")
        self.refused("recorded tree omits", self.build("ignored.test"))
        (self.repo.root / "extra_ignored.go").unlink()
        self.repo.write("fixture.go", 'package bindingfixture\n\nconst Version = "edited"\n')
        self.refused("not clean", current)

    def test_linux_docker_takes_no_source(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_driver(self.build("linux.test"), profile="linux-docker")
        self.assertFalse((self.root / "output").exists())

    def test_linux_docker_never_binds(self):
        test_binary, launches = self.build("linux.test"), []

        def run_bounded(command, env, log_path, timeout):
            launches.append(command)
            return 1

        environment = {"QGF_SOURCE_COMMIT": self.repo.head(), "QGF_SOURCE_TREE": self.repo.tree(),
                       "QGF_IMAGE_ID": "sha256:" + "0" * 64}
        argv = ["run.py", "--profile", "linux-docker", "--zero-vectors", "--binary", str(test_binary), "--test-binary", str(test_binary),
                "--output", str(self.root / "output")]
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, environment))
            stack.enter_context(mock.patch.object(sys, "argv", argv))
            stack.enter_context(mock.patch.object(runner.platform, "system", return_value="Linux"))
            stack.enter_context(mock.patch.object(runner.platform, "machine", return_value="x86_64"))
            stack.enter_context(mock.patch.object(runner.shutil, "which", return_value="/usr/bin/stand-in"))
            stack.enter_context(mock.patch.object(runner.subprocess, "check_output",
                                                  return_value="go version go1.27.4 linux/amd64\n"))
            stack.enter_context(mock.patch.object(runner, "run_bounded", side_effect=run_bounded))
            stack.enter_context(mock.patch.object(runner.candidate_binding, "bind",
                                                  side_effect=AssertionError("bound on linux-docker")))
            with self.assertRaisesRegex(ValueError, "peer control exited 1"):
                runner.main()
        self.assertEqual(len(launches), 1)
        identity = json.loads((self.root / "output" / "attempt.json").read_text())["identity"]
        self.assertNotIn("source", identity)
        self.assertNotIn("test_binary_binding", identity)


if __name__ == "__main__":
    unittest.main()
