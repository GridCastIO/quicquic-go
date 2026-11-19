import contextlib
import copy
import io
import json
import os
import shutil
import signal
import stat
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

import ordinary_cost as c1
import topology_comparison as driver
import test_candidate_binding as binding_fixture

CANDIDATE = "0" * 40

# A stand-in for udprelay: it reports one ephemeral front per configured route, relays
# until stdin closes and publishes a record. FAKE_RELAY selects a failure.
FAKE_RELAY = r'''
import json, os, sys, time
args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
with open(os.environ["FAKE_PIDS"], "a") as f:
    f.write(f"{os.getpid()}\n")
mode = os.environ.get("FAKE_RELAY", "ok")
config = json.load(open(args["-config"]))
if mode == "silent":
    time.sleep(3600)
routes = [r["name"] for r in config["routes"]]
if mode == "wrong-routes":
    routes = routes[:1]
print(json.dumps({"version": 1, "fronts": {r: f"127.0.0.1:{4000 + i}" for i, r in enumerate(routes)}}), flush=True)
sys.stdin.read()
if mode == "exit":
    sys.exit(3)
json.dump({"config": config, "routes": []}, open(args["-record"], "w"))
'''

# A stand-in for the root test binary's role entrypoint. FAKE_ROLE=<role>:<failure>
# selects one role's failure.
FAKE_TEST = r'''
import json, os, sys, time
spec = json.loads(os.environ["TOPOLOGY_COMPARISON_SPEC"])
with open(os.environ["FAKE_PIDS"], "a") as f:
    f.write(f"{os.getpid()}\n")
role = spec["role"]
failing, _, failure = os.environ.get("FAKE_ROLE", "").partition(":")
if failing == role and failure == "hang":
    time.sleep(3600)
if failing == role and failure == "exit":
    sys.exit(1)
def metric(value, unit):
    return {"value": value, "unit": unit, "source": "fixture producer", "available": True}
if role == "relay-config":
    routes = ["a", "b", "competitor"] if spec["topology"] == "shared" else ["a", "b"]
    result = {"kind": spec["topology"], "server": spec["server"], "routes": [{"name": r} for r in routes]}
elif role == "verify":
    identity = {k: spec[k] for k in ("topology", "arm", "controller", "seed", "server")}
    relay = json.load(open(spec["relay_record"]))
    profile = os.environ["FAKE_PROFILE"]
    goos, goarch = profile.split("-")
    result = {
        "version": 1, "identity": identity, "platform": {"profile": profile, "goos": goos, "goarch": goarch},
        "relay": {"config": relay["config"], "routes": [
            {"name": r["name"], "forward": {"dropped": 0, "overflow": 0}, "reverse": {"overflow": 0}} for r in relay["config"]["routes"]]},
        "server": {"self_cpu": metric(5, "ns"), "peak_rss_end": metric(9, os.environ["FAKE_RSS_UNIT"]),
                   "useful_bytes": metric(1000, "bytes"),
                   "flows": {"focal-1": {"stream_useful_bytes": 800, "datagram_useful_bytes": 200, "max_receive_gap_ns": 7,
                                         "datagram_latency": {"count": 2, "p50_us": 2.0, "p99_us": 3.0, "max_us": 3.0},
                                         "object_completion": {"count": 0, "p50_us": 0, "p99_us": 0, "max_us": 0}}}},
        "client": {"self_cpu": metric(4, "ns")},
        "workload_failures": [],
    }
    if spec["topology"] == "shared":
        empty = {"count": 0, "p50_us": 0, "p99_us": 0, "max_us": 0}
        result["server"]["flows"]["competitor"] = {"stream_useful_bytes": 300, "datagram_useful_bytes": 0, "max_receive_gap_ns": 9,
                                                   "datagram_latency": empty, "object_completion": empty}
    if failing == role and failure == "no-competitor":
        del result["server"]["flows"]["competitor"]
        result["workload_failures"] = ["competitor: no useful STREAM delivery"]
    if failing == role and failure == "workload":
        result["workload_failures"] = ["focal-1: no useful STREAM delivery"]
    if failing == role and failure == "no-cpu":
        result["client"]["self_cpu"] = {"value": None, "unit": "ns", "source": "x", "available": False, "reason": "none"}
    if failing == role and failure == "other-arm":
        result["identity"]["arm"] = "pair"
else:
    result = {"role": role}
print("--- PASS: TestTopologyComparisonRole (0.01s)")
json.dump(result, open(spec["output"], "w"))
'''


def executable(path, source):
    path.write_text(f"#!{sys.executable}\n" + textwrap.dedent(source))
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie still answers; only an unreaped child would remain one.
    return True


def stub_binding(source, candidate, binaries, tree=None):
    return {"source": {"commit": candidate, "tree": "b" * 40, "head_tree": "b" * 40, "clean": True},
            "bindings": {name: {"method": "stub"} for name in binaries}}


class Fixture:
    def __init__(self, root, profile):
        self.root = root
        self.profile = profile
        self.relay = executable(root / "udprelay", FAKE_RELAY)
        self.test = executable(root / "fixture.test", FAKE_TEST)
        self.pids = root / "pids"
        self.pids.touch()

    def run(self, *extra, env=None, timeout="30"):
        output = self.root / "output"
        argv = ["--test-binary", str(self.test), "--relay-binary", str(self.relay), "--candidate", CANDIDATE,
                "--output", str(output), "--platform-profile", self.profile, "--timeout-seconds", timeout, *extra]
        system, machine = c1.PROFILES[self.profile]["host"]
        environment = {"FAKE_PIDS": str(self.pids), "FAKE_PROFILE": self.profile,
                       "FAKE_RSS_UNIT": c1.PROFILES[self.profile]["rss_unit"], **(env or {})}
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, environment))
            stack.enter_context(mock.patch.object(driver.platform, "system", return_value=system))
            stack.enter_context(mock.patch.object(driver.platform, "machine", return_value=machine))
            stack.enter_context(mock.patch.object(c1, "binary_identity", side_effect=lambda path: {"path": str(Path(path).resolve())}))
            # Stand-in executables: the binding is exercised by NativeBindingTests, and a Linux
            # profile must never reach it.
            stack.enter_context(mock.patch.object(driver.candidate_binding, "bind", side_effect=(
                stub_binding if self.profile == c1.DARWIN else AssertionError("bound off Darwin"))))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            code = driver.main(argv)
        summary = json.loads((output / "summary.json").read_text())
        records = [json.loads(line) for line in (output / "observations.jsonl").read_text().splitlines()]
        return code, summary, records

    def launched(self):
        return [int(line) for line in self.pids.read_text().split()]


class ExecutionTests(unittest.TestCase):
    def test_arms_run_in_order_and_record_relay_cpu(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary), c1.DARWIN)
            code, summary, records = fixture.run("--topology", "shared", "--arm", "pair", "--arm", "single-a")
            self.assertEqual(code, 0, summary)
            self.assertTrue(summary["passed"])
            self.assertFalse(summary["judged"])
            self.assertEqual(summary["evidence_class"], driver.EVIDENCE_CLASS[c1.DARWIN])
            self.assertEqual([o["arm"] for o in summary["observations"]], ["pair", "single-a"])
            for record, observation in zip(records, summary["observations"]):
                self.assertEqual(record["status"], "succeeded")
                self.assertEqual(observation["status"], "succeeded", "both outputs carry the terminal status")
                self.assertEqual(record["exit"], {"relay": 0, "server": 0, "client": 0})
                self.assertTrue(record["relay_cpu"]["available"])
                self.assertEqual(record["relay_cpu"]["source"], driver.RELAY_CPU_SOURCE)
                self.assertEqual(observation["relay_cpu_ns"], record["relay_cpu"]["value"])
                self.assertEqual(set(observation["relay_drops"]), {"a", "b", "competitor"})
                self.assertIn("competitor_share", observation)
                self.assertEqual(observation["flows"]["focal-1"]["datagram_latency"]["count"], 2)
                self.assertIsNone(observation["flows"]["focal-1"]["object_completion"], "an empty histogram has no percentile")
            self.assertTrue(all(Path(p).is_absolute() for p in (records[0]["launched"]["test"], records[0]["launched"]["relay"])))
            self.assertFalse(any(alive(pid) for pid in fixture.launched()))

    def test_failure_fails_the_run_and_reaps_every_child(self):
        for name, env in (("client hangs", {"FAKE_ROLE": "client:hang"}),
                          ("server exits", {"FAKE_ROLE": "server:exit"}),
                          ("relay never ready", {"FAKE_RELAY": "silent"}),
                          ("relay fronts", {"FAKE_RELAY": "wrong-routes"}),
                          ("relay exit", {"FAKE_RELAY": "exit"}),
                          ("verify fails", {"FAKE_ROLE": "verify:exit"}),
                          ("missing metric", {"FAKE_ROLE": "verify:no-cpu"}),
                          ("other arm", {"FAKE_ROLE": "verify:other-arm"}),
                          ("workload failure", {"FAKE_ROLE": "verify:workload"})):
            with self.subTest(name), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary), c1.DARWIN)
                with mock.patch.object(driver, "RELAY_READY_S", 2), mock.patch.object(driver, "SETUP_S", 0), \
                        mock.patch.dict(driver.MODES, smoke=(0, 1)):
                    code, summary, records = fixture.run("--topology", "disjoint", "--arm", "single-a", env=env, timeout="13")
                self.assertEqual(code, 1)
                self.assertFalse(summary["passed"])
                if name != "workload failure":
                    self.assertEqual(records[0]["status"], "failed")
                    self.assertTrue(records[0]["error"])
                self.assertTrue(fixture.launched())
                self.assertFalse(any(alive(pid) for pid in fixture.launched()), name)
                if records[0].get("exit"):
                    self.assertTrue(all(code is not None for code in records[0]["exit"].values()))

    def test_failed_relay_config_charges_time_and_launches_no_relay(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary), c1.DARWIN)
            code, summary, records = fixture.run("--topology", "disjoint", "--arm", "single-a",
                                                 env={"FAKE_ROLE": "relay-config:exit"})
            self.assertEqual(code, 1)
            self.assertEqual(records[0]["status"], "failed")
            self.assertGreater(records[0]["occupied_s"], 0)
            self.assertEqual(set(records[0]["launched"]), {"test"}, "no relay process existed")
            for key, value in (("topology", "disjoint"), ("arm", "single-a"), ("controller", "bbrv3")):
                self.assertEqual(records[0][key], value, "an early failure is still identifiable")
            self.assertEqual(summary["observations"][0]["arm"], "single-a")
            self.assertEqual(summary["observations"][0]["topology"], "disjoint")
            self.assertEqual((summary["controller"], summary["seed"]), ("bbrv3", driver.BASE_SEED))
            self.assertFalse(any(alive(pid) for pid in fixture.launched()))

    def test_silent_competitor_keeps_the_measurements_and_fails_the_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary), c1.DARWIN)
            code, summary, records = fixture.run("--topology", "shared", "--arm", "single-a",
                                                 env={"FAKE_ROLE": "verify:no-competitor"})
            self.assertEqual(code, 1)
            observation = summary["observations"][0]
            self.assertEqual((observation["competitor_stream_bytes"], observation["competitor_share"]), (0, 0.0))
            self.assertEqual(observation["focal_stream_bytes"], 800)
            self.assertEqual(observation["workload_failures"], ["competitor: no useful STREAM delivery"])
            self.assertEqual(records[0]["status"], "succeeded", "a valid observation with a workload failure")

    def test_cancellation_during_publication_is_honored_after_it(self):
        written = []
        real = driver.json.dumps

        def interrupted(value, *args, **kwargs):
            # A SIGTERM as the ledger row is serialized, outside any wait.
            if isinstance(value, dict) and value.get("arm") == "single-a" and "status" in value and not written:
                written.append(True)
                os.kill(os.getpid(), signal.SIGTERM)
            return real(value, *args, **kwargs)
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary), c1.DARWIN)
            with mock.patch.object(driver.json, "dumps", side_effect=interrupted):
                code, summary, records = fixture.run("--topology", "disjoint", "--arm", "single-a", "--arm", "pair",
                                                     env={"FAKE_ROLE": "relay-config:exit"})
            self.assertEqual(code, 1)
            self.assertEqual([(r["arm"], r["status"]) for r in records], [("single-a", "failed")], "the row is published")
            self.assertEqual([o["arm"] for o in summary["observations"]], ["single-a"], "no later arm runs")
            self.assertIn("SIGTERM", summary["error"])

    def test_cancellation_during_failed_cleanup_still_cancels(self):
        # The runner may inherit an ignored SIGINT, which DeferredInterrupts preserves.
        self.addCleanup(signal.signal, signal.SIGINT, signal.signal(signal.SIGINT, signal.default_int_handler))
        with self.assertRaises(KeyboardInterrupt) as raised:
            with driver.deferred_interrupts():
                os.kill(os.getpid(), signal.SIGINT)  # outside a wait: recorded, not raised
                raise ValueError("role failed")
        self.assertIsInstance(raised.exception.__cause__, ValueError, "the failure stays the cause")

    def test_cancellation_after_a_failed_role_keeps_its_exit_as_cause(self):
        self.addCleanup(signal.signal, signal.SIGINT, signal.signal(signal.SIGINT, signal.default_int_handler))
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary), c1.DARWIN)
            real_read = Path.read_text
            queued = []

            def read_then_cancel(path, *args, **kwargs):
                # The role has been reaped and the wait disarmed; this read builds its exit error.
                if not queued:
                    queued.append(True)
                    os.kill(os.getpid(), signal.SIGINT)
                return real_read(path, *args, **kwargs)
            environment = {"FAKE_PIDS": str(fixture.pids), "FAKE_ROLE": "relay-config:exit"}
            with mock.patch.dict(os.environ, environment), \
                    mock.patch.object(Path, "read_text", read_then_cancel), self.assertRaises(KeyboardInterrupt) as raised:
                driver.run_role(fixture.test, dict(os.environ), {"role": "relay-config", "output": str(fixture.root / "c.json")},
                                fixture.root / "c.log", 10, {})
            self.assertTrue(queued)
            self.assertIsInstance(raised.exception.__cause__, ValueError)
            self.assertIn("relay-config exit 1", str(raised.exception.__cause__))

    def test_cancelled_arm_leaves_a_terminal_row_and_stops_the_run(self):
        def cancelled(*args):
            raise KeyboardInterrupt("SIGTERM") from ValueError("server exit 1")
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary), c1.DARWIN)
            with mock.patch.object(driver, "run_observation", side_effect=cancelled) as run:
                code, summary, records = fixture.run("--topology", "disjoint", "--arm", "single-a", "--arm", "pair")
            self.assertEqual(code, 1)
            self.assertEqual(run.call_count, 1, "no later arm launches after cancellation")
            self.assertEqual([(r["arm"], r["status"]) for r in records], [("single-a", "failed")])
            self.assertIn("KeyboardInterrupt", records[0]["error"])
            self.assertIn("server exit 1", records[0]["cause"])
            self.assertEqual([(o["arm"], o["status"]) for o in summary["observations"]], [("single-a", "failed")])
            self.assertFalse(summary["passed"])

    def test_observation_accepted_after_its_deadline_fails(self):
        class Clock:
            late = False

            def monotonic(self):
                return time.monotonic() + (10**6 if self.late else 0)

            def __getattr__(self, name):
                return getattr(time, name)
        clock = Clock()
        check = driver.check_observation

        def slow_readback(*args):
            check(*args)
            clock.late = True
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary), c1.DARWIN)
            with mock.patch.object(driver, "time", clock), mock.patch.object(driver, "SETUP_S", 0), \
                    mock.patch.object(driver, "check_observation", side_effect=slow_readback), \
                    mock.patch.dict(driver.MODES, smoke=(0, 1)):
                code, summary, records = fixture.run("--topology", "disjoint", "--arm", "single-a")
            self.assertEqual(code, 1)
            self.assertEqual(records[0]["status"], "failed")
            self.assertIn("deadline", records[0]["error"])
            self.assertGreaterEqual(records[0]["occupied_s"], 10**6, "readback is charged")

    def test_refused_arms_launch_nothing(self):
        for profile, extra in ((c1.DARWIN, ("--arm", "primary-backup")),
                               (c1.DARWIN, ("--arm", "aggregate")),
                               (c1.LINUX, ("--arm", "aggregate", "--controller", "reno")),
                               (c1.LINUX, ("--arm", "pair", "--arm", "pair")),
                               (c1.LINUX, ("--arm", "pair", "--mode", "diagnostic"))):
            with self.subTest(profile=profile, extra=extra), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary), profile)
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    fixture.run("--topology", "disjoint", *extra, timeout="30")
                self.assertEqual(fixture.launched(), [])

    def test_linux_admits_every_public_arm(self):
        for arm in driver.ARMS:
            for controller in driver.CONTROLLERS:
                reason = driver.refusal(c1.LINUX, arm, controller)
                self.assertEqual(reason is not None, arm == "aggregate" and controller == "reno", (arm, controller))


def observation(profile=c1.LINUX):
    goos, goarch = c1.PROFILES[profile]["identity"]
    metric = lambda value, unit: {"value": value, "unit": unit, "source": "fixture producer", "available": True}
    return {
        "version": 1,
        "identity": {"topology": "shared", "arm": "pair", "controller": "bbrv3", "seed": 1, "server": "127.0.0.1:9"},
        "platform": {"profile": profile, "goos": goos, "goarch": goarch},
        "relay": {"config": {"kind": "shared"}},
        "server": {"self_cpu": metric(1, "ns"), "peak_rss_end": metric(2, c1.PROFILES[profile]["rss_unit"]),
                   "useful_bytes": metric(3, "bytes"),
                   "flows": {"focal-1": {"datagram_latency": {"count": 2, "p50_us": 1.0, "p99_us": 2.0, "max_us": 2.0},
                                         "object_completion": {"count": 0, "p50_us": 0, "p99_us": 0, "max_us": 0}}}},
        "client": {"self_cpu": metric(1, "ns")},
        "workload_failures": [],
    }


class RecordTests(unittest.TestCase):
    expected = {"topology": "shared", "arm": "pair", "controller": "bbrv3", "seed": 1, "server": "127.0.0.1:9"}

    def test_valid_observation(self):
        driver.check_observation(observation(), self.expected, c1.LINUX)

    def test_missing_identity_or_metric_fails(self):
        for name, edit in (("version", lambda o: o.update(version=2)),
                           ("arm identity", lambda o: o["identity"].pop("arm")),
                           ("topology identity", lambda o: o["identity"].update(topology="disjoint")),
                           ("relay record", lambda o: o.pop("relay")),
                           ("platform", lambda o: o.update(platform={"profile": c1.DARWIN})),
                           ("self cpu", lambda o: o["client"].pop("self_cpu")),
                           ("rss unit", lambda o: o["server"]["peak_rss_end"].update(unit="bytes")),
                           ("unavailable useful bytes", lambda o: o["server"].update(
                               useful_bytes={"value": None, "unit": "bytes", "source": "x", "available": False, "reason": "r"})),
                           ("latency count", lambda o: o["server"]["flows"]["focal-1"]["datagram_latency"].pop("count")),
                           ("empty latency", lambda o: o["server"]["flows"]["focal-1"].update(object_completion={})),
                           ("latency p99", lambda o: o["server"]["flows"]["focal-1"]["datagram_latency"].pop("p99_us")),
                           ("failures", lambda o: o.pop("workload_failures"))):
            with self.subTest(name):
                record = copy.deepcopy(observation())
                edit(record)
                with self.assertRaises(ValueError):
                    driver.check_observation(record, self.expected, c1.LINUX)

    def test_relay_cpu_is_the_drivers_observation(self):
        good = {"value": 10, "unit": "ns", "source": driver.RELAY_CPU_SOURCE, "available": True}
        driver.check_relay_cpu(good)
        for bad in (dict(good, source="relay self-report"), dict(good, value=None, available=False, reason="x"), dict(good, unit="s")):
            with self.assertRaises(ValueError):
                driver.check_relay_cpu(bad)

    def test_role_alarm_covers_the_remaining_time(self):
        self.assertIn("-test.timeout=2s", driver.role_command("bin", 1.2))

    def test_ready_line_names_exactly_the_routes(self):
        fronts = {"a": "127.0.0.1:1", "b": "127.0.0.1:2"}
        self.assertEqual(driver.check_ready({"version": 1, "fronts": fronts}, "disjoint"), fronts)
        for ready, topology in (({"version": 1, "fronts": fronts}, "shared"),
                                ({"version": 2, "fronts": fronts}, "disjoint"),
                                ({"version": 1, "fronts": dict(fronts, b="0.0.0.0:2")}, "disjoint"),
                                ({"version": 1, "fronts": fronts, "extra": 1}, "disjoint")):
            with self.assertRaises(ValueError):
                driver.check_ready(ready, topology)


class NativeBindingTests(unittest.TestCase):
    """MP-MAC #1528: on darwin-arm64 the driver refuses a test or relay binary that is not
    a byte-identical rebuild of the clean candidate, before any output or launch."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.repo = binding_fixture.FixtureRepo(self.root)

    def build(self, prefix):
        return (self.repo.build(f"{prefix}.test", tags="ordinarycost"),
                self.repo.build(f"{prefix}-udprelay", test=False, package="./cmd/tool"))

    def run_driver(self, binaries, candidate=None, profile=c1.DARWIN):
        launches, real_popen = [], driver.subprocess.Popen
        test, relay = binaries

        def popen(command, *args, **kwargs):
            if Path(command[0]).resolve() in (Path(test).resolve(), Path(relay).resolve()):
                launches.append(command)
                raise OSError("launch spy: nothing runs in a binding test")
            return real_popen(command, *args, **kwargs)

        system, machine = c1.PROFILES[profile]["host"]
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(c1, "GO_VERSION", binding_fixture.GO_VERSION))
            stack.enter_context(mock.patch.object(driver.platform, "system", return_value=system))
            stack.enter_context(mock.patch.object(driver.platform, "machine", return_value=machine))
            stack.enter_context(mock.patch.object(driver.subprocess, "Popen", side_effect=popen))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            code = driver.main(["--platform-profile", profile, "--test-binary", str(test), "--relay-binary", str(relay),
                                "--candidate", candidate or self.repo.head(), "--source", str(self.repo.root),
                                "--controller", "bbrv3", "--topology", "disjoint", "--arm", "single-a", "--seed", "1493",
                                "--mode", "diagnostic", "--timeout-seconds", "135", "--output", str(self.root / "output")])
        return code, launches

    def refused(self, pattern, binaries, candidate=None):
        with self.assertRaisesRegex(ValueError, pattern):
            self.run_driver(binaries, candidate)
        self.assertFalse((self.root / "output").exists(), "refused before any output")

    def test_candidate_builds_are_accepted_and_recorded(self):
        code, launches = self.run_driver(self.build("bound"))
        self.assertEqual(code, 1)
        self.assertEqual(len(launches), 1, "the bound binaries reached their first launch")
        identity = json.loads((self.root / "output" / "identity.json").read_text())
        self.assertEqual(identity["source"], {"commit": self.repo.head(), "tree": self.repo.tree(),
                                              "head_tree": self.repo.tree(), "clean": True})
        for name, form in (("test", "test"), ("relay", "build")):
            bound = identity["binaries"][name]["binding"]
            self.assertEqual((bound["sha256"], bound["form"], bound["rebuild"]),
                             (identity["binaries"][name]["sha256"], form, "byte-identical"))

    def test_stale_dirty_mismatched_or_ignored_builds_are_refused(self):
        first = self.repo.head()
        test, relay = self.build("first")
        self.repo.stale("advance.test")
        fresh_test, fresh_relay = self.build("fresh")
        self.refused("is not the candidate's build", (test, fresh_relay))
        self.refused("is not the candidate's build", (fresh_test, relay))
        self.refused("not the candidate", (fresh_test, fresh_relay), candidate=first)
        self.repo.write("extra_ignored.go", "package bindingfixture\n\nconst Extra = 1\n")
        self.refused("recorded tree omits", self.build("ignored"))
        (self.repo.root / "extra_ignored.go").unlink()
        self.repo.write("fixture.go", 'package bindingfixture\n\nconst Version = "edited"\n')
        self.refused("not clean", (fresh_test, fresh_relay))

    def test_linux_profile_takes_no_source(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_driver(self.build("linux"), profile=c1.LINUX)
        self.assertFalse((self.root / "output").exists())


VERDICT_CANDIDATE = "c" * 40
VERDICT_SEEDS = {1: 1493, 2: 1593, 3: 1693}


def run_record(topology, arm, controller, seed, useful, competitor=300):
    """A succeeded observations.jsonl record as the driver writes it."""
    rss = {"value": 2, "unit": "bytes", "source": "fixture producer", "available": True}
    cpu = {"value": 1, "unit": "ns", "source": "fixture producer", "available": True}
    latency = {"count": 4, "p50_us": 10.0, "p99_us": 20.0, "max_us": 30.0}
    flows = {"focal-1": {"stream_useful_bytes": useful - 100, "datagram_useful_bytes": 100, "max_receive_gap_ns": 5,
                         "datagram_latency": latency, "object_completion": latency}}
    routes = ["a", "b"]
    if topology == "shared":
        routes.append("competitor")
        flows["competitor"] = {"stream_useful_bytes": competitor, "datagram_useful_bytes": 0, "max_receive_gap_ns": 9,
                               "datagram_latency": dict(latency, count=0), "object_completion": latency}
    observation = {
        "version": 1, "identity": {"topology": topology, "arm": arm, "controller": controller, "seed": seed, "server": "127.0.0.1:9",
                                   "start_at_unix_ns": 1, "warmup_ns": 10 * 10**9, "window_ns": 60 * 10**9},
        "platform": {"profile": c1.DARWIN, "goos": "darwin", "goarch": "arm64"},
        "relay": {"config": {"kind": topology}, "routes": [
            {"name": route, "forward": {"dropped": 0, "overflow": 0}, "reverse": {"overflow": 0}} for route in routes]},
        "server": {"self_cpu": cpu, "peak_rss_end": rss, "useful_bytes": {**cpu, "value": useful, "unit": "bytes"}, "flows": flows},
        "client": {"self_cpu": cpu}, "workload_failures": [],
    }
    return {"launched": {}, "status": "succeeded", "topology": topology, "arm": arm, "controller": controller, "seed": seed,
            "platform_profile": c1.DARWIN, "occupied_s": 80.0, "process_cpu_s": {}, "exit": {},
            "relay_cpu": {"value": 3, "unit": "ns", "source": driver.RELAY_CPU_SOURCE, "available": True},
            "observation": observation}


class DarwinVerdictTests(unittest.TestCase):
    """MP-MAC #1569 (protocol D12 A): the X13 verdict from the verified summary of each
    accepted run; medians of round-paired ratios, never ratios of medians."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def run_directory(self, key, useful=1000, competitor=300, edit=None, identity_edit=None, summary_edit=None):
        parts = key.split("/")
        controller, (topology, arm, n) = ("reno", parts[1:]) if parts[0] == "reno" else ("bbrv3", parts)
        n = int(n)
        directory = self.root / "topology" / key.replace("/", "_") / "a1"
        directory.mkdir(parents=True)
        record = run_record(topology, arm, controller, VERDICT_SEEDS[n], useful, competitor)
        if edit:
            edit(record)
        row = dict(driver.summarize(record), status="succeeded") if record["status"] == "succeeded" else \
            {"topology": topology, "arm": arm, "status": "failed", "error": record["error"]}
        summary = {"version": 1, "passed": row["status"] == "succeeded" and not row.get("workload_failures"),
                   "judged": False, "judgment": driver.NOT_JUDGED, "mode": "diagnostic", "platform_profile": c1.DARWIN,
                   "evidence_class": driver.EVIDENCE_CLASS[c1.DARWIN], "topology": topology, "controller": controller,
                   "seed": VERDICT_SEEDS[n], "observations": [row]}
        identity = {"version": 1, "candidate": VERDICT_CANDIDATE, "platform_profile": c1.DARWIN, "topology": topology,
                    "arms": [arm], "controller": controller, "mode": "diagnostic", "seed": VERDICT_SEEDS[n],
                    "warmup_s": 10, "window_s": 60,
                    "binaries": {name: {"path": f"/bin/{name}", "sha256": digit * 64,
                                        "binding": {"method": "rebuild-from-candidate/v1", "sha256": digit * 64}}
                                 for name, digit in (("test", "9"), ("relay", "8"))},
                    "source": {"commit": VERDICT_CANDIDATE, "tree": "7" * 40, "head_tree": "7" * 40, "clean": True}}
        if identity_edit:
            identity_edit(identity)
        if summary_edit:
            summary_edit(summary)
        (directory / "identity.json").write_text(json.dumps(identity))
        (directory / "summary.json").write_text(json.dumps(summary))
        (directory / "observations.jsonl").write_text(json.dumps(record) + "\n")
        return directory

    def inventory(self, useful=None, competitor=None, changes=None, unequal=False, reno=False):
        """Every judged run; useful and competitor map (topology, arm) to per-N values."""
        useful, competitor, changes = useful or {}, competitor or {}, changes or {}
        attempts = {}
        for topology in ("disjoint", "shared"):
            for arm in driver.ARMS:
                for n in (1, 2, 3):
                    key = f"{topology}/{arm}/{n}"
                    values = useful.get((topology, arm), (1000, 1000, 1000))
                    rivals = competitor.get(arm, (300, 300, 300))
                    attempts[key] = self.run_directory(key, values[n - 1], rivals[n - 1], **changes.get(key, {}))
        extra = ([f"unequal/{arm}/1" for arm in driver.ARMS] if unequal else []) + \
            ([f"reno/{topology}/primary-backup/1" for topology in ("disjoint", "shared")] if reno else [])
        for key in extra:
            attempts[key] = self.run_directory(key, **changes.get(key, {}))
        return attempts

    @staticmethod
    def inventory_keys():
        return [f"{topology}/{arm}/{n}" for topology in ("disjoint", "shared") for arm in driver.ARMS for n in (1, 2, 3)]

    def verdict(self, attempts, profile=c1.DARWIN):
        output = self.root / "verdict"
        argv = ["--verdict", "--platform-profile", profile, "--output", str(output)]
        for key, directory in attempts.items():
            argv += ["--attempt", f"{key}={directory}"]
        with contextlib.redirect_stdout(io.StringIO()):
            code = driver.main(argv)
        return code, json.loads((output / "verdict.json").read_text())

    def refused(self, pattern, attempts, profile=c1.DARWIN):
        with self.assertRaisesRegex(ValueError, pattern):
            self.verdict(attempts, profile)
        self.assertFalse((self.root / "verdict").exists(), "a refusal writes no verdict")

    def gates(self, verdict):
        return {gate["name"]: gate for gate in verdict["gates"]}

    def judged(self, aggregate, single_a=(100,) * 3, single_b=(100,) * 3, pair=(100,) * 3,
               competitor_aggregate=(90,) * 3, competitor_pair=(100,) * 3):
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir()
        useful = {("disjoint", "aggregate"): aggregate, ("disjoint", "single-a"): single_a,
                  ("disjoint", "single-b"): single_b, ("disjoint", "pair"): pair}
        return self.verdict(self.inventory(useful, {"aggregate": competitor_aggregate, "pair": competitor_pair}))

    def test_gates_pass_exactly_at_their_thresholds_and_fail_just_below(self):
        code, verdict = self.judged((120, 120, 120), pair=(126, 126, 126))
        gates = self.gates(verdict)
        self.assertEqual((code, verdict["passed"]), (0, True))
        self.assertEqual(gates["disjoint aggregate / better single"]["median"], 1.2)
        self.assertEqual(gates["shared competitor beside aggregate / beside pair"]["median"], 0.9)
        code, verdict = self.judged((114, 114, 114), single_a=(95,) * 3, single_b=(95,) * 3, pair=(120,) * 3)
        self.assertEqual((code, self.gates(verdict)["disjoint aggregate / pair"]["median"]), (0, 0.95))
        for case, expected in ((dict(aggregate=(119, 119, 119)), "disjoint aggregate / better single"),
                               (dict(aggregate=(120, 120, 120), pair=(127, 127, 127)), "disjoint aggregate / pair"),
                               (dict(aggregate=(120, 120, 120), competitor_aggregate=(89, 89, 89)),
                                "shared competitor beside aggregate / beside pair")):
            with self.subTest(expected=expected):
                code, verdict = self.judged(**case)
                self.assertEqual((code, verdict["passed"]), (1, False))
                self.assertEqual([name for name, gate in self.gates(verdict).items() if not gate["passed"]], [expected])

    def test_better_single_is_chosen_first_and_a_tie_goes_to_single_a(self):
        _, verdict = self.judged((120, 120, 120), single_a=(100, 90, 110), single_b=(90, 100, 105))
        self.assertEqual(verdict["better_single"]["arm"], "single-a")
        self.assertEqual(verdict["better_single"]["median_useful_bytes"], {"single-a": 100, "single-b": 100})
        _, verdict = self.judged((120, 120, 120), single_a=(99, 99, 99), single_b=(100, 100, 100))
        self.assertEqual(verdict["better_single"]["arm"], "single-b")
        # Round-paired with the chosen arm only, never round by round with whichever is larger.
        _, verdict = self.judged((132, 132, 132), single_a=(100, 100, 120), single_b=(110, 110, 110))
        self.assertEqual(verdict["better_single"]["arm"], "single-b")
        self.assertEqual(self.gates(verdict)["disjoint aggregate / better single"]["rounds"], {"1": 1.2, "2": 1.2, "3": 1.2})

    def test_median_of_ratios_fails_where_a_ratio_of_medians_would_pass(self):
        code, verdict = self.judged((120, 300, 100), single_a=(100, 300, 90), single_b=(1, 1, 1))
        gate = self.gates(verdict)["disjoint aggregate / better single"]
        self.assertAlmostEqual(gate["median"], 100 / 90)
        self.assertFalse(gate["passed"])  # medians alone, 120 / 100, would read 1.20
        self.assertEqual(code, 1)

    def test_zero_denominator_or_failed_input_never_passes(self):
        code, verdict = self.judged((120, 120, 120), pair=(0, 126, 126))
        gate = self.gates(verdict)["disjoint aggregate / pair"]
        self.assertEqual((code, gate["passed"], gate["median"]), (1, False, None))
        self.assertIn("round 1: zero denominator", gate["reasons"])

        def failed(record):
            record.update(status="failed", error="ValueError: relay exit 3")

        def workload(record):
            record["observation"]["workload_failures"] = ["focal-1: no useful STREAM delivery"]

        for edit, reason in ((failed, "ValueError: relay exit 3"), (workload, "no useful STREAM delivery")):
            with self.subTest(reason=reason):
                shutil.rmtree(self.root, ignore_errors=True)
                self.root.mkdir()
                code, verdict = self.verdict(self.inventory(changes={"shared/pair/2": {"edit": edit}}))
                gate = self.gates(verdict)["shared competitor beside aggregate / beside pair"]
                self.assertEqual((code, verdict["passed"], gate["passed"]), (1, False, False))
                self.assertTrue(any("shared/pair/2" in item and reason in item for item in gate["reasons"]), gate["reasons"])
                self.assertTrue(self.gates(verdict)["disjoint aggregate / pair"]["passed"])

    def test_wrong_seed_or_mismatched_identity_is_refused(self):
        for key, change, pattern in (
                ("disjoint/aggregate/2", {"identity_edit": lambda i: i.update(seed=1493)}, "seed 1493 is not 1593"),
                ("shared/pair/3", {"identity_edit": lambda i: i.update(candidate="d" * 40)}, "candidate"),
                ("shared/pair/3", {"identity_edit": lambda i: i["binaries"]["relay"].update(sha256="6" * 64)}, "binding|relay"),
                ("disjoint/single-b/1", {"identity_edit": lambda i: i.update(arms=["single-a"])}, "arm"),
                ("disjoint/single-b/1", {"identity_edit": lambda i: i.update(mode="smoke")}, "diagnostic"),
                ("disjoint/pair/1", {"identity_edit": lambda i: i.update(controller="reno")}, "controller"),
                ("disjoint/pair/1", {"identity_edit": lambda i: i.update(platform_profile=c1.LINUX)}, "darwin-arm64"),
                ("disjoint/pair/1", {"identity_edit": lambda i: i.pop("source")}, "binding"),
                ("disjoint/pair/1", {"summary_edit": lambda s: s["observations"][0].update(useful_bytes=5000)}, "unverified")):
            with self.subTest(key=key, pattern=pattern):
                shutil.rmtree(self.root, ignore_errors=True)
                self.root.mkdir()
                self.refused(pattern, self.inventory(changes={key: change}))

    def test_a_missing_digest_is_not_a_binding(self):
        def unbound(identity):
            for binary in identity["binaries"].values():
                binary.update(sha256=None, binding={})

        attempts = self.inventory(changes={key: {"identity_edit": unbound} for key in self.inventory_keys()})
        self.refused("binding", attempts)

    def test_every_run_is_measured_on_the_diagnostic_timeline(self):
        def smoke_observation(record):
            record["observation"]["identity"].update(warmup_ns=10**9, window_ns=5 * 10**9)

        for change, pattern in (({"summary_edit": lambda summary: summary.update(mode="smoke")}, "summary mode"),
                                ({"identity_edit": lambda identity: identity.update(warmup_s=1, window_s=5)}, "timeline"),
                                ({"edit": smoke_observation}, "timeline")):
            with self.subTest(pattern=pattern, change=sorted(change)):
                shutil.rmtree(self.root, ignore_errors=True)
                self.root.mkdir()
                self.refused(pattern, self.inventory(changes={"shared/pair/2": change}))

    def test_malformed_input_shapes_name_their_file(self):
        for name, malform in (("summary.json", lambda text: json.dumps(json.loads(text) | {"observations": ["row"]})),
                              ("identity.json", lambda text: "[]"), ("observations.jsonl", lambda text: "[]\n")):
            with self.subTest(name=name):
                shutil.rmtree(self.root, ignore_errors=True)
                self.root.mkdir()
                attempts = self.inventory()
                path = attempts["disjoint/single-b/3"] / name
                path.write_text(malform(path.read_text()))
                self.refused(f"disjoint/single-b/3 .*{name}", attempts)

    def test_input_set_is_exact(self):
        attempts = self.inventory({("disjoint", "aggregate"): (1300, 1300, 1300)}, unequal=True, reno=True)
        code, verdict = self.verdict(attempts)
        self.assertEqual(code, 0)
        self.assertEqual(sorted(verdict["reported"]["unequal"]), sorted(driver.ARMS))
        self.assertEqual(sorted(verdict["reported"]["reno"]), ["disjoint", "shared"])
        self.assertEqual(len(verdict["inputs"]), 37)
        self.assertEqual(verdict["reported"]["disjoint"]["aggregate"]["2"]["focal_datagram_bytes"], 100)
        self.assertEqual(verdict["reported"]["disjoint"]["aggregate"]["2"]["object_completion"]["focal-1"]["count"], 4)
        shutil.rmtree(self.root / "verdict")
        for missing in ("disjoint/aggregate/3", "unequal/pair/1", "reno/shared/primary-backup/1"):
            with self.subTest(missing=missing):
                self.refused("inventory", {key: value for key, value in attempts.items() if key != missing})
        self.refused("inventory", attempts | {"disjoint/aggregate/4": attempts["disjoint/aggregate/3"]})
        self.refused("darwin-arm64", attempts, profile=c1.LINUX)


if __name__ == "__main__":
    unittest.main()
