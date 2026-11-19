import contextlib
import copy
import io
import json
import os
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
        with self.assertRaises(KeyboardInterrupt) as raised:
            with driver.deferred_interrupts():
                os.kill(os.getpid(), signal.SIGINT)  # outside a wait: recorded, not raised
                raise ValueError("role failed")
        self.assertIsInstance(raised.exception.__cause__, ValueError, "the failure stays the cause")

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


if __name__ == "__main__":
    unittest.main()
