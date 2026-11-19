import copy
import hashlib
import time
import unittest
import tempfile
import contextlib
import io
import subprocess
import os
import select
import signal
import sys
import textwrap
import json
import re
import shutil
from pathlib import Path
from unittest import mock

import ordinary_cost as driver
import test_candidate_binding as binding_fixture
import powermetrics_wrapper
from test_powermetrics_wrapper import alive, fake_powermetrics, wait_gone, wrapper_command


def flow(label="ordinary", bytes_per_second=1000, control_p99=1000.0):
    return {
        "label": label,
        "series": [bytes_per_second] * driver.WINDOW_S,
        "useful_bytes": bytes_per_second * driver.WINDOW_S,
        "control": {"count": 6000, "p99_us": control_p99} if label == "ordinary" else None,
        "timeout_close": False,
        "close_cause": "",
        "multipath_negotiated": False,
    }


def metric(value, unit, source="fixture producer", **extra):
    return {"value": value, "unit": unit, "source": source, "available": True, **extra}


def unavailable(unit, reason="no producer", source="fixture producer"):
    return {"value": None, "unit": unit, "source": source, "available": False, "reason": reason}


# The collector strings the C1 Go producers emit, written out independently of the driver.
CPU_SOURCE = "getrusage(RUSAGE_SELF) user+system time, window end minus start"
LOST_SOURCE = "ConnectionStats().PacketsLost"
USEFUL_SOURCE = "receiver-counted application bytes in the window, every flow"
RSS_SOURCE = {"linux-amd64": "/proc/self/status VmHWM", "darwin-arm64": "getrusage(RUSAGE_SELF).ru_maxrss"}


def identity(platform):
    goos, goarch = driver.PROFILES[platform]["identity"]
    return {"profile": platform, "goos": goos, "goarch": goarch}


def lost(controller):
    if controller == "reno":
        return metric(0, "packets", LOST_SOURCE)
    return unavailable("packets", "only Reno/CUBIC counts lost packets", LOST_SOURCE)


def observation(cell="stream-gso-on", profile="unregistered", round_=0, platform="linux-amd64", controller="reno", **changes):
    linux = platform == "linux-amd64"
    rss_unit, scale = ("kB", 1024) if linux else ("bytes", 1)
    rss = 1000 if linux else 1024000
    connection = {"label": "ordinary", "timeout_close": False, "close_cause": "", "controller": controller,
                  "multipath_negotiated": False, "packets_lost_metric": lost(controller)}
    if controller == "reno":
        connection["packets_lost"] = 0
    cells = list(driver.PROFILES[platform]["cells"])
    record = {
        "cell": cell,
        "profile": profile,
        "round": round_,
        "seed": driver.BASE_SEED + 100 * cells.index(cell) + round_,
        "mode": "campaign" if linux else "smoke",
        "platform_profile": platform,
        "controller": controller,
        "server": {
            "go": driver.GO_VERSION,
            "controller": controller,
            "platform": identity(platform),
            "granted": profile == "opted-in",
            "multipath_advertised": linux and profile == "opted-in",
            "gso_capable": linux and cell not in ("stream-gso-off", "datagram-batch-off"),
            "window_cpu_s": 60.0,
            "self_cpu": metric(60 * 10**9, "ns", CPU_SOURCE),
            "peak_rss_at_sample": metric(rss, rss_unit, RSS_SOURCE[platform], bytes=rss * scale),
            "peak_rss_end": metric(rss, rss_unit, RSS_SOURCE[platform], bytes=rss * scale),
            "write_errors": 0,
            "joined": profile == "opted-in",
            "application_send_call_boundary": driver.METRIC_BOUNDARIES["application_send_call"],
            "application_send_call": {"ordinary": {"count": 6000, "p99_us": 1000.0}},
            "connections": [connection],
        },
        "client": {"go": driver.GO_VERSION, "controller": controller, "platform": identity(platform),
                   "window_cpu_s": 30.0, "self_cpu": metric(30 * 10**9, "ns", CPU_SOURCE), "flows": [flow()]},
    }
    if linux:
        record["contaminated"] = False
        record["server"].update(rss_kb_at_20s=1000, rss_kb_end=1000)
    else:
        record["host_activity"] = {"status": "unavailable", "reason": "no host sampler selected"}
    if cell == "mixed-bulk":
        if profile == "opted-in":
            background = flow("background", 2000)
            background["multipath_negotiated"] = True
            background["paths"] = ["live", "live"]
            record["client"]["flows"].append(background)
        else:
            record["client"]["flows"] += [flow("background"), flow("background")]
    if cell == "stateless-pressure":
        record["client"]["flood"] = {"sent": 600000, "resets": 300000}
    record["client"]["useful_bytes"] = metric(sum(f["useful_bytes"] for f in record["client"]["flows"]), "bytes", USEFUL_SOURCE)
    record.update(changes)
    return record


def campaign():
    return [observation(cell, profile, round_) for cell, round_, profile, _ in driver.schedule()]


def pair_rounds(cell="stream-gso-on", opted=None):
    """Three matched rounds; opted edits each opted-in record."""
    pairs = []
    for round_ in range(driver.ROUNDS):
        control = observation(cell, "unregistered", round_)
        treated = observation(cell, "opted-in", round_)
        if opted:
            opted(treated)
        pairs.append((control, treated))
    return pairs


def idle(record, index):
    background = record["client"]["flows"][index]
    background["series"] = [0] * driver.WINDOW_S
    background["useful_bytes"] = 0
    resync_useful(record)


def resync_useful(record):
    record["client"]["useful_bytes"]["value"] = sum(f["useful_bytes"] for f in record["client"]["flows"])


def scale_goodput(record, factor):
    for item in record["client"]["flows"]:
        if item["label"] == "ordinary":
            item["series"] = [int(value * factor) for value in item["series"]]
            item["useful_bytes"] = sum(item["series"])
    resync_useful(record)


class ScheduleTests(unittest.TestCase):
    def test_thirty_six_fixed_instances(self):
        instances = driver.schedule()
        self.assertEqual(len(instances), 36)
        self.assertEqual(len({instance[:3] for instance in instances}), 36)
        self.assertEqual(len(driver.CELLS), 6)

    def test_profile_order_alternates_by_round(self):
        for round_ in range(driver.ROUNDS):
            pair = [i for i in driver.schedule() if i[0] == "mixed-bulk" and i[1] == round_]
            first = "unregistered" if round_ % 2 == 0 else "opted-in"
            self.assertEqual(pair[0][2], first)

    def test_pair_shares_its_seed_and_rounds_differ(self):
        seeds = {}
        for cell, round_, profile, seed in driver.schedule():
            seeds.setdefault((cell, round_), set()).add(seed)
        self.assertTrue(all(len(pair) == 1 for pair in seeds.values()))
        self.assertEqual(len({next(iter(pair)) for pair in seeds.values()}), 18)

    def test_only_off_arms_disable_acceleration(self):
        disabled = {name for name, cell in driver.CELLS.items() if cell["env"]}
        self.assertEqual(disabled, {"stream-gso-off", "datagram-batch-off"})


class AccountingTests(unittest.TestCase):
    def test_complete_campaign_passes(self):
        driver.check_accounting(campaign())

    def test_missing_or_duplicate_instance_fails(self):
        records = campaign()
        for bad in (records[1:], records + records[:1], []):
            with self.subTest(count=len(bad)), self.assertRaisesRegex(ValueError, "instances"):
                driver.check_accounting(bad)

    def test_wrong_toolchain_fails(self):
        record = observation()
        record["server"]["go"] = "go1.26.11"
        with self.assertRaisesRegex(ValueError, "toolchain"):
            driver.check_observation(record)

    def test_short_series_fails(self):
        record = observation()
        record["client"]["flows"][0]["series"].pop()
        with self.assertRaisesRegex(ValueError, "seconds"):
            driver.check_observation(record)

    def test_useful_bytes_must_match_series(self):
        record = observation()
        record["client"]["flows"][0]["useful_bytes"] += 1
        with self.assertRaisesRegex(ValueError, "useful bytes"):
            driver.check_observation(record)

    def test_profile_must_match_grant(self):
        record = observation(profile="opted-in")
        record["server"]["granted"] = False
        with self.assertRaisesRegex(ValueError, "grant"):
            driver.check_observation(record)
        record = observation(profile="unregistered")
        record["server"]["granted"] = True
        with self.assertRaisesRegex(ValueError, "grant"):
            driver.check_observation(record)

    def test_opted_in_must_return_write_authority(self):
        record = observation(profile="opted-in")
        record["server"]["joined"] = False
        with self.assertRaisesRegex(ValueError, "join"):
            driver.check_observation(record)

    def test_acceleration_must_match_cell(self):
        record = observation("stream-gso-on")
        record["server"]["gso_capable"] = False
        with self.assertRaisesRegex(ValueError, "acceleration"):
            driver.check_observation(record)
        record = observation("stream-gso-off")
        record["server"]["gso_capable"] = True
        with self.assertRaisesRegex(ValueError, "acceleration"):
            driver.check_observation(record)

    def test_mixed_baseline_must_represent_the_workload(self):
        record = observation("mixed-bulk", "unregistered")
        del record["client"]["flows"][2]
        resync_useful(record)
        with self.assertRaisesRegex(ValueError, "two independent"):
            driver.check_observation(record)
        record = observation("mixed-bulk", "opted-in")
        record["client"]["flows"][1]["multipath_negotiated"] = False
        with self.assertRaisesRegex(ValueError, "two-path"):
            driver.check_observation(record)
        record = observation("mixed-bulk", "opted-in")
        for paths in (["live"], ["live", "closed"]):
            record["client"]["flows"][1]["paths"] = paths
            with self.subTest(paths=paths), self.assertRaisesRegex(ValueError, "two-path"):
                driver.check_observation(record)

    def test_idle_background_is_a_workload_failure_not_a_record_error(self):
        """A valid record may show an idle background flow: the Reno thresholds judge it,
        and an unjudged smoke counts it as a failed workload."""
        for profile, index in (("opted-in", 1), ("unregistered", 2)):
            for controller in ("reno", "bbrv3"):
                record = observation("mixed-bulk", profile, controller=controller)
                idle(record, index)
                with self.subTest(profile=profile, controller=controller):
                    driver.check_observation(record)
                    self.assertEqual(driver.workload_failures(record),
                                     [f"{profile}: background delivered no useful bytes"])

    def test_stateless_cell_must_apply_pressure(self):
        record = observation("stateless-pressure")
        record["client"]["flood"]["sent"] = 0
        with self.assertRaisesRegex(ValueError, "pressure"):
            driver.check_observation(record)

    def test_missing_latency_samples_fail(self):
        record = observation()
        record["client"]["flows"][0]["control"]["count"] = 0
        with self.assertRaisesRegex(ValueError, "control"):
            driver.check_observation(record)
        record = observation()
        record["server"]["application_send_call"]["ordinary"]["count"] = 0
        with self.assertRaisesRegex(ValueError, "application send-call"):
            driver.check_observation(record)


class JudgmentTests(unittest.TestCase):
    def test_equal_profiles_pass(self):
        verdict = driver.judge_cell("stream-gso-on", pair_rounds())
        self.assertTrue(verdict["passed"], verdict["failures"])
        self.assertEqual(verdict["goodput_ratio"]["median"], 1.0)

    def test_goodput_floor_is_ninety_five_percent(self):
        for factor, passes in ((0.95, True), (0.94, False)):
            verdict = driver.judge_cell("stream-gso-on", pair_rounds(opted=lambda r: scale_goodput(r, factor)))
            with self.subTest(factor=factor):
                self.assertEqual(verdict["passed"], passes)

    def test_cpu_ceiling_is_one_hundred_ten_percent(self):
        def cpu(value):
            return lambda record: record["server"].update(window_cpu_s=value)

        self.assertTrue(driver.judge_cell("stream-gso-on", pair_rounds(opted=cpu(66.0)))["passed"])
        self.assertFalse(driver.judge_cell("stream-gso-on", pair_rounds(opted=cpu(66.5)))["passed"])

    def test_cpu_counts_all_useful_bytes_of_the_endpoint(self):
        def more_background(record):
            record["client"]["flows"][1]["series"] = [4000] * driver.WINDOW_S
            record["client"]["flows"][1]["useful_bytes"] = 4000 * driver.WINDOW_S

        verdict = driver.judge_cell("mixed-bulk", pair_rounds("mixed-bulk", more_background))
        # Control delivers 3,000 B/s and opted-in 5,000 B/s for the same CPU.
        self.assertAlmostEqual(verdict["cpu_per_useful_byte_ratio"]["median"], 0.6)

    def test_latency_limit_is_the_larger_allowance(self):
        def latency(value):
            def apply(record):
                record["client"]["flows"][0]["control"]["p99_us"] = value
            return apply

        # A 1,000 us baseline allows baseline + 1 ms, which is the larger.
        self.assertTrue(driver.judge_cell("stream-gso-on", pair_rounds(opted=latency(2000.0)))["passed"])
        self.assertFalse(driver.judge_cell("stream-gso-on", pair_rounds(opted=latency(2001.0)))["passed"])

        def slow_base(rounds):
            for control, _ in rounds:
                control["client"]["flows"][0]["control"]["p99_us"] = 20000.0
            return rounds

        # A 20 ms baseline allows 110%, which is the larger.
        self.assertTrue(driver.judge_cell("stream-gso-on", slow_base(pair_rounds(opted=latency(22000.0))))["passed"])
        self.assertFalse(driver.judge_cell("stream-gso-on", slow_base(pair_rounds(opted=latency(22001.0))))["passed"])

    def test_application_send_call_is_judged_separately(self):
        def slow(record):
            record["server"]["application_send_call"]["ordinary"]["p99_us"] = 5000.0

        verdict = driver.judge_cell("stream-gso-on", pair_rounds(opted=slow))
        self.assertFalse(verdict["passed"])
        self.assertIn("application send-call p99", verdict["failures"][0])

    def test_median_decides_and_range_reports(self):
        rounds = pair_rounds()
        scale_goodput(rounds[0][1], 0.5)
        scale_goodput(rounds[2][1], 1.1)
        verdict = driver.judge_cell("stream-gso-on", rounds)
        self.assertTrue(verdict["passed"], verdict["failures"])
        self.assertEqual(verdict["goodput_ratio"]["range"], [0.5, 1.1])

    def test_timeout_close_fails_in_any_round(self):
        rounds = pair_rounds()
        rounds[1][1]["client"]["flows"][0]["timeout_close"] = True
        verdict = driver.judge_cell("stream-gso-on", rounds)
        self.assertFalse(verdict["passed"])
        self.assertIn("timeout", verdict["failures"][0])
        rounds = pair_rounds()
        rounds[1][1]["server"]["connections"][0]["timeout_close"] = True
        self.assertFalse(driver.judge_cell("stream-gso-on", rounds)["passed"])

    def test_unbounded_memory_fails_in_any_round(self):
        rounds = pair_rounds()
        rounds[0][1]["server"]["rss_kb_end"] = 1101
        verdict = driver.judge_cell("stream-gso-on", rounds)
        self.assertFalse(verdict["passed"])
        self.assertIn("memory", verdict["failures"][0])
        rounds = pair_rounds()
        rounds[0][1]["server"]["rss_kb_end"] = 1100
        self.assertTrue(driver.judge_cell("stream-gso-on", rounds)["passed"])

    def test_empty_second_breaks_fair_progress(self):
        rounds = pair_rounds("mixed-bulk")
        background = rounds[2][1]["client"]["flows"][1]
        background["series"][30] = 0
        background["useful_bytes"] = sum(background["series"])
        verdict = driver.judge_cell("mixed-bulk", rounds)
        self.assertFalse(verdict["passed"])
        self.assertIn("fair progress", verdict["failures"][0])

    def test_control_starvation_is_reported_not_judged(self):
        rounds = pair_rounds()
        control = rounds[0][0]["client"]["flows"][0]
        control["series"][3] = 0
        control["useful_bytes"] = sum(control["series"])
        verdict = driver.judge_cell("stream-gso-on", rounds)
        self.assertTrue(verdict["passed"], verdict["failures"])
        self.assertEqual(verdict["empty_seconds"]["unregistered"], [1, 0, 0])

    def test_ordinary_and_background_are_reported_separately(self):
        verdict = driver.judge_cell("mixed-bulk", pair_rounds("mixed-bulk"))
        self.assertEqual(verdict["background_bytes"]["unregistered"], [2000 * driver.WINDOW_S] * 3)
        self.assertEqual(verdict["background_bytes"]["opted-in"], [2000 * driver.WINDOW_S] * 3)

    def test_stateless_share_is_reported(self):
        rounds = pair_rounds("stateless-pressure")
        verdict = driver.judge_cell("stateless-pressure", rounds)
        self.assertEqual(verdict["stateless_reset_share"]["opted-in"], [0.5, 0.5, 0.5])

    def test_summary_lists_every_cell(self):
        summary = driver.summarize(campaign())
        self.assertEqual(sorted(summary["cells"]), sorted(driver.CELLS))
        self.assertTrue(summary["passed"])

    def test_one_failed_cell_fails_the_summary(self):
        records = copy.deepcopy(campaign())
        for record in records:
            if record["cell"] == "mixed-bulk" and record["profile"] == "opted-in":
                scale_goodput(record, 0.5)
        summary = driver.summarize(records)
        self.assertFalse(summary["passed"])
        self.assertEqual(summary["failed_cells"], ["mixed-bulk"])


class ContaminationTests(unittest.TestCase):
    def test_limit_scales_with_the_observation(self):
        self.assertAlmostEqual(driver.foreign_limit_s(70), 3.5)

    def test_contaminated_pair_reruns_once(self):
        clean, dirty = {"contaminated": False}, {"contaminated": True}
        self.assertFalse(driver.rerun_due([clean, clean], attempt=0, reruns_used=0))
        self.assertTrue(driver.rerun_due([clean, dirty], attempt=0, reruns_used=0))
        self.assertFalse(driver.rerun_due([clean, dirty], attempt=1, reruns_used=1))

    def test_rerun_budget_is_finite(self):
        dirty = {"contaminated": True}
        self.assertFalse(driver.rerun_due([dirty, dirty], attempt=0, reruns_used=driver.MAX_RERUN_PAIRS))

    def test_rerun_never_reads_a_result(self):
        # The rule sees only the contamination flag, whatever the goodput says.
        slow = {"contaminated": False, "client": {"flows": [{"useful_bytes": 0}]}}
        self.assertFalse(driver.rerun_due([slow, slow], attempt=0, reruns_used=0))

    def test_flagged_observation_is_reported(self):
        records = campaign()
        records[0]["contaminated"] = True
        summary = driver.summarize(records)
        self.assertEqual(summary["contaminated_observations"], 1)
        self.assertFalse(summary["passed"], "unreplaced contamination cannot qualify")


class ExecutionTests(unittest.TestCase):
    def invoke(self, root, extra=(), failure=None, edit=None, platform="linux-amd64", sampler=None, role_s=0):
        binary = root / "fixture"
        binary.write_bytes(b"fixture identity")
        real_popen = subprocess.Popen
        output = root / "output"
        processes = []

        class Process:
            returncode = None

            def wait(self, timeout=None):
                time.sleep(role_s)
                if failure == "timeout" and timeout is not None:
                    raise subprocess.TimeoutExpired("fixture", timeout)
                self.returncode = 7 if failure == "exit" else 0
                return self.returncode

            def kill(self):
                self.returncode = -9

        def launch(command, env=None, stdout=None, **kwargs):
            if env is None or "ORDINARY_COST_SPEC" not in env:
                return real_popen(command, stdout=stdout, **kwargs)
            if failure == "launch" and processes:
                raise OSError("second child launch failed")
            spec = json.loads(env["ORDINARY_COST_SPEC"])
            process = Process()
            processes.append(process)
            stdout.write("--- PASS: TestOrdinaryCostRole (0.01s)\n")
            record = observation(spec["cell"], spec["profile"], platform=platform, controller=spec["controller"])
            for argument in command:
                if argument.startswith("-test.cpuprofile=") and failure != "missing-profile":
                    Path(argument.split("=", 1)[1]).write_bytes(b"profile")
            if edit:
                edit(record)
            if failure != "missing":
                Path(spec["output"]).write_text(json.dumps(record[spec["role"]]))
            return process

        with contextlib.ExitStack() as stack:
            for name, value in (("wait_quiet", {}), ("schedstat_running_ns", dict.fromkeys(driver.FIXTURE_CPUS, 0)),
                                ("softirqd_ns", 0)):
                stack.enter_context(mock.patch.object(driver, name, return_value=value))
            system, machine = driver.PROFILES[platform]["host"]
            stack.enter_context(mock.patch.object(driver.platform, "platform", return_value=f"{system}-test"))
            stack.enter_context(mock.patch.object(driver.platform, "system", return_value=system))
            stack.enter_context(mock.patch.object(driver.platform, "machine", return_value=machine))
            if sampler is not None:
                stack.enter_context(mock.patch.object(driver, "powermetrics_command", return_value=sampler))
            # Stand-in binaries: the binding itself is exercised by NativeBindingTests, and a
            # Linux profile must never reach it.
            stack.enter_context(mock.patch.object(driver.candidate_binding, "bind", side_effect=(
                stub_binding if platform == driver.DARWIN else AssertionError("bound off Darwin"))))
            stack.enter_context(mock.patch.object(driver.shutil, "which", return_value="taskset"))
            stack.enter_context(mock.patch.object(driver.subprocess, "run", return_value=mock.Mock(stdout=f"fixture: {driver.GO_VERSION}\n")))
            stack.enter_context(mock.patch.object(driver.subprocess, "Popen", side_effect=launch))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            code = driver.main(["--candidate", "a" * 40, "--binary", str(binary), "--output", str(output),
                                "--remaining-instances", "42", "--remaining-host-seconds", "6000",
                                "--timeout-seconds", "135", *extra])
        return code, json.loads((output / "summary.json").read_text()), processes

    def exercise_sigterm_during_roles(self, native=False):
        """Real process ownership, fake workload: interrupt only after main starts waiting.
        The native profile also owns a host sampler, which must be reaped too."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "fixture").write_bytes(b"fake-role fixture")
            bootstrap = textwrap.dedent("""
                import json, os, subprocess, sys
                from pathlib import Path
                from types import SimpleNamespace
                sys.path.insert(0, sys.argv[3])
                import ordinary_cost as driver
                root, ready = Path(sys.argv[1]), int(sys.argv[2])
                pids = []
                class FakeRole(subprocess.Popen):
                    def __init__(self, command, **kwargs):
                        # Roles wait for a signal; the sampler stops when its stdin closes.
                        child = "import sys; sys.stdin.read()" if command == ["sampler"] else "import signal; signal.pause()"
                        super().__init__([sys.executable, "-c", child], **kwargs)
                        pids.append(self.pid)
                        (root / "pids.json").write_text(json.dumps(pids))
                    def wait(self, timeout=None):
                        if timeout is not None:
                            os.write(ready, b"waiting")
                        code = super().wait(timeout=timeout)
                        with (root / "reaped.txt").open("a") as file:
                            file.write(str(self.pid) + "\\n")
                        return code
                driver.subprocess.Popen = FakeRole
                driver.subprocess.run = lambda *a, **kw: SimpleNamespace(stdout="fixture: " + driver.GO_VERSION + "\\n")
                native = sys.argv[4] == "native"
                driver.platform.system = lambda: "Darwin" if native else "Linux"
                driver.platform.machine = lambda: "arm64" if native else "x86_64"
                driver.platform.platform = lambda: "test"
                driver.powermetrics_command = lambda: ["sampler"]
                driver.shutil.which = lambda _: "taskset"
                driver.wait_quiet = lambda _: {}
                driver.schedstat_running_ns = lambda: dict.fromkeys(driver.FIXTURE_CPUS, 0)
                driver.softirqd_ns = lambda: 0
                driver.candidate_binding.bind = lambda source, candidate, binaries, tree=None: {
                    "source": {"commit": candidate, "tree": "b" * 40, "head_tree": "b" * 40, "clean": True},
                    "bindings": {name: {"method": "stub"} for name in binaries}}
                extra = ["--platform-profile", "darwin-arm64", "--smoke-cell", "stream", "--host-sampler", "powermetrics"] if native else []
                sys.exit(driver.main([
                    "--candidate", "a" * 40, "--binary", str(root / "fixture"), "--output", str(root / "output"),
                    "--remaining-instances", "36", "--remaining-host-seconds", "5000", "--timeout-seconds", "135", *extra,
                ]))
            """)
            read_fd, write_fd = os.pipe()
            process = subprocess.Popen([sys.executable, "-c", bootstrap, str(root), str(write_fd),
                                        str(Path(driver.__file__).parent), "native" if native else "linux"], pass_fds=(write_fd,),
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            os.close(write_fd)
            pids = []
            try:
                ready, _, _ = select.select([read_fd], [], [], 10)
                self.assertTrue(ready, "driver did not reach the role wait")
                self.assertEqual(os.read(read_fd, 7), b"waiting")
                pids = json.loads((root / "pids.json").read_text())
                self.assertEqual(len(pids), 3 if native else 2)
                process.send_signal(signal.SIGTERM)
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 1, stderr.decode())
                summary = json.loads((root / "output" / "summary.json").read_text())
                self.assertFalse(summary["passed"])
                self.assertEqual(summary["instances_charged"], 1)
                self.assertEqual(summary["attempts"][0]["status"], "failed")
                self.assertIn("SIGTERM", summary["attempts"][0]["error"])
                self.assertGreater(summary["host_seconds_charged"], 0)
                self.assertCountEqual([int(pid) for pid in (root / "reaped.txt").read_text().splitlines()], pids)
                for pid in pids:
                    with self.assertRaises(ProcessLookupError):
                        os.kill(pid, 0)
            finally:
                os.close(read_fd)
                if process.poll() is None:
                    process.kill()
                process.communicate()
                # Also clean up a deliberately failing pre-fix driver reproduction.
                for pid in pids:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_failed_child_or_check_retains_charge_and_reaps_peers(self):
        for failure in ("launch", "exit", "timeout", "missing", "invalid", "baseline-write", "baseline-close", "baseline-timeout"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                def invalidate(record):
                    if failure == "invalid":
                        record["server"]["application_send_call"]["ordinary"]["p99_us"] = float("nan")
                    elif failure == "baseline-write":
                        record["server"]["write_errors"] = 1
                    else:
                        record["client"]["flows"][0].update(close_cause="failed connection", timeout_close=failure == "baseline-timeout")
                code, summary, processes = self.invoke(Path(temporary), failure=failure,
                                                       edit=invalidate if failure == "invalid" or failure.startswith("baseline-") else None)
                self.assertEqual(code, 1)
                self.assertEqual(summary["instances_charged"], 1)
                self.assertGreater(summary["host_seconds_charged"], 0)
                self.assertEqual(summary["attempts"][0]["status"], "failed")
                self.assertTrue(summary["attempts"][0]["error"])
                self.assertTrue(all(process.returncode is not None for process in processes))
                self.assertFalse(summary["campaign_complete"])
        self.exercise_sigterm_during_roles()

    def test_insufficient_allowance_launches_nothing(self):
        for extra in (("--remaining-instances", "35"), ("--remaining-host-seconds", "100")):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as temporary:
                code, summary, processes = self.invoke(Path(temporary), extra)
                self.assertEqual(code, 1)
                self.assertEqual(processes, [])
                self.assertEqual(summary["instances_charged"], 0)
                self.assertIn("insufficient", summary["error"])

    def test_campaign_tolerance_failure_exits_nonzero(self):
        for failure in ("goodput", "idle background", "write", "close", "timeout"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                def fail(record):
                    if record["cell"] != "mixed-bulk" or record["profile"] != driver.OPTED_IN:
                        return
                    if failure == "goodput":
                        scale_goodput(record, 0.5)
                    elif failure == "idle background":
                        idle(record, 1)  # judged by the existing fair-progress rule
                    elif failure == "write":
                        record["server"]["write_errors"] = 1
                    else:
                        record["server"]["connections"][0].update(close_cause="failed connection", timeout_close=failure == "timeout")
                code, summary, _ = self.invoke(Path(temporary), edit=fail)
                self.assertEqual(code, 1)
                self.assertEqual(summary["failed_cells"], ["mixed-bulk"])
                self.assertEqual(summary["instances_charged"], 36)
                self.assertTrue(summary["campaign_complete"])
                self.assertEqual(sorted(driver.CELLS), sorted(summary["cells"]))
                self.assertFalse(summary["cells"]["mixed-bulk"]["passed"])

    def test_bbr_diagnostic_selects_and_records_both_roles(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            code, summary, processes = self.invoke(root, ("--diagnostic-cell", "stateless-pressure", "--controller", "bbrv3"))
            self.assertEqual(code, 0)
            self.assertEqual(len(processes), 4)
            self.assertEqual(summary["controller"], "bbrv3")
            self.assertTrue(summary["timing_eligible"])
            records = [json.loads(line) for line in (root / "output" / "diagnostic.jsonl").read_text().splitlines()]
            for record in records:
                self.assertEqual(record["controller"], "bbrv3")
                for role in ("server", "client"):
                    self.assertEqual(record[role]["controller"], "bbrv3")
            with self.assertRaises(ValueError):
                driver.check_accounting(records)

    def test_controller_mismatch_keeps_failed_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            def mismatch(record):
                record["client"]["controller"] = "reno"
            code, summary, _ = self.invoke(Path(temporary),
                ("--diagnostic-cell", "stateless-pressure", "--controller", "bbrv3"), edit=mismatch)
            self.assertEqual(code, 1)
            self.assertEqual(summary["instances_charged"], 1)
            self.assertIn("controller", summary["error"])

    def test_profiling_requires_both_profiles_and_is_not_timing_evidence(self):
        for failure in (None, "missing-profile"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                code, summary, _ = self.invoke(root,
                    ("--diagnostic-cell", "stateless-pressure", "--controller", "bbrv3", "--cpu-profile"), failure=failure)
                self.assertEqual(code, int(failure is not None))
                self.assertTrue(summary["cpu_profile"])
                self.assertFalse(summary["timing_eligible"])
                if failure:
                    self.assertIn("missing CPU profile", summary["error"])
                    self.assertEqual(summary["instances_charged"], 1)
                else:
                    records = [json.loads(line) for line in (root / "output" / "diagnostic.jsonl").read_text().splitlines()]
                    for record in records:
                        self.assertFalse(record["timing_eligible"])
                        self.assertEqual(set(record["cpu_profiles"]), {"server", "client"})
                        for path in record["cpu_profiles"].values():
                            self.assertTrue(Path(path).is_file())

    def test_bbr_runs_every_linux_workload_outside_the_campaign(self):
        for cell in ("stream-gso-on", "datagram-batch-on", "mixed-bulk"):
            with self.subTest(cell=cell), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                code, summary, processes = self.invoke(root, ("--smoke-cell", cell, "--controller", "bbrv3"))
                self.assertEqual(code, 0, summary.get("error"))
                self.assertEqual(len(processes), 4)
                records = [json.loads(line) for line in (root / "output" / "smoke.jsonl").read_text().splitlines()]
                for record in records:
                    for connection in record["server"]["connections"]:
                        self.assertFalse(connection["packets_lost_metric"]["available"])
                self.assertEqual(summary["observations"]["packets_lost"], {"unregistered": [None], "opted-in": [None]})

    def test_only_reno_and_the_historical_bbr_diagnostic_are_judged(self):
        def slow(record):
            if record["profile"] == driver.OPTED_IN:
                scale_goodput(record, 0.5)

        for controller, cell, judged in (("bbrv3", "mixed-bulk", False), ("bbrv3", "stream-gso-on", False),
                                         ("bbrv3", "stateless-pressure", True), ("reno", "mixed-bulk", True)):
            with self.subTest(controller=controller, cell=cell), tempfile.TemporaryDirectory() as temporary:
                code, summary, _ = self.invoke(Path(temporary), ("--smoke-cell", cell, "--controller", controller), edit=slow)
                self.assertEqual(summary["judged"], judged)
                self.assertEqual(code, int(judged), summary.get("error"))
                self.assertEqual(summary["passed"], not judged)
                if judged:
                    self.assertFalse(summary["diagnostic"]["passed"])
                else:
                    self.assertIn("observations", summary["judgment"])
                    self.assertNotIn("diagnostic", summary)
                    self.assertEqual(summary["workload_failures"], [])
                    self.assertTrue({"passed", "failures"}.isdisjoint(summary["observations"]))
                    self.assertLess(summary["observations"]["goodput_ratio"]["median"], 0.95, "the ratio is still reported")

    def test_unjudged_bbr_smoke_fails_on_a_failed_transfer(self):
        def broken(failure):
            def edit(record):
                if record["profile"] != driver.OPTED_IN:
                    return
                if failure == "write":
                    record["server"]["write_errors"] = 1
                elif failure == "timeout":
                    record["client"]["flows"][0]["timeout_close"] = True
                else:
                    record["server"]["connections"][0]["close_cause"] = "failed connection"
            return edit

        for failure in ("write", "close", "timeout"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                code, summary, _ = self.invoke(Path(temporary), ("--smoke-cell", "stream-gso-on", "--controller", "bbrv3"),
                                               edit=broken(failure))
                self.assertEqual(code, 1, summary.get("error"))
                self.assertFalse(summary["judged"])
                self.assertTrue(summary["workload_failures"])

    def test_unjudged_bbr_mixed_bulk_fails_on_an_idle_background_flow(self):
        def edit(record):
            if record["profile"] == driver.OPTED_IN:
                idle(record, 1)

        with tempfile.TemporaryDirectory() as temporary:
            code, summary, _ = self.invoke(Path(temporary), ("--smoke-cell", "mixed-bulk", "--controller", "bbrv3"),
                                           edit=edit)
        self.assertEqual(code, 1, summary)
        self.assertFalse(summary["passed"])
        self.assertNotIn("error", summary)
        self.assertEqual(summary["workload_failures"], ["opted-in: background delivered no useful bytes"])

    def test_unsupported_bbr_or_profiling_campaign_launches_nothing(self):
        for extra in (("--controller", "bbrv3"),
                      ("--cpu-profile",),
                      ("--smoke-cell", "stream"),
                      ("--host-sampler", "powermetrics", "--smoke-cell", "stream-gso-on")):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                    self.invoke(root, extra)
                self.assertEqual(caught.exception.code, 2)
                self.assertFalse((root / "output").exists())

    def test_diagnostic_is_charged_and_cannot_complete_campaign(self):
        for option in ("--smoke-cell", "--diagnostic-cell"):
            with self.subTest(option=option), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                code, summary, _ = self.invoke(root, (option, "stateless-pressure"))
                self.assertEqual(code, 0)
                self.assertEqual(summary["instances_charged"], 2)
                self.assertFalse(summary["campaign_complete"])
                self.assertNotEqual(summary["mode"], "campaign")
                self.assertIn("neither native return nor peer delivery", summary["metric_boundaries"]["application_send_call"])
                self.assertEqual(summary["diagnostic"]["stateless_offered_packets"][driver.OPTED_IN], [600000])
                records = [json.loads(line) for line in (root / "output" / f"{summary['mode']}.jsonl").read_text().splitlines()]
                with self.assertRaises(ValueError):
                    driver.check_accounting(records)



class RevalidationTests(unittest.TestCase):
    """An affected-cell rerun of the Reno inventory, as B5 reran mixed bulk (#1044)."""

    def test_affected_cell_revalidation_reruns_only_that_cell(self):
        instances = driver.schedule(["mixed-bulk"])
        self.assertEqual(6, len(instances))
        self.assertEqual({"mixed-bulk"}, {cell for cell, _, _, _ in instances})
        records = [observation(cell, profile, round_) for cell, round_, profile, _ in instances]
        summary = driver.summarize(records, ["mixed-bulk"])
        self.assertEqual(["mixed-bulk"], sorted(summary["cells"]))
        with self.assertRaisesRegex(ValueError, "do not match"):
            driver.check_accounting(records)
        with self.assertRaisesRegex(ValueError, "not in the inventory"):
            driver.schedule(["no-such-cell"])


class MetricRecordTests(unittest.TestCase):
    """Every metric names its unit and producer, and an unavailable one has no value."""

    def test_reno_zero_is_a_counted_zero(self):
        record = observation()
        driver.check_observation(record)
        rounds = pair_rounds()
        self.assertEqual(driver.judge_cell("stream-gso-on", rounds)["packets_lost"]["opted-in"], [0, 0, 0])

    def test_bbr_loss_stays_unavailable(self):
        record = observation(cell="stateless-pressure", controller="bbrv3")
        driver.check_observation(record)
        self.assertNotIn("packets_lost", record["server"]["connections"][0])
        verdict = driver.judge_cell("stateless-pressure", [(record, observation("stateless-pressure", "opted-in", controller="bbrv3"))])
        self.assertEqual(verdict["packets_lost"], {"unregistered": [None], "opted-in": [None]})

    def test_fabricated_or_missing_loss_fails(self):
        record = observation(controller="bbrv3")
        record["server"]["connections"][0]["packets_lost_metric"] = metric(0, "packets", LOST_SOURCE)
        with self.assertRaisesRegex(ValueError, "lost"):
            driver.check_observation(record)
        record = observation(controller="bbrv3")
        record["server"]["connections"][0]["packets_lost"] = 0
        with self.assertRaisesRegex(ValueError, "lost"):
            driver.check_observation(record)
        record = observation()
        record["server"]["connections"][0]["packets_lost_metric"] = unavailable("packets", source=LOST_SOURCE)
        with self.assertRaisesRegex(ValueError, "lost"):
            driver.check_observation(record)

    def test_malformed_metric_fails(self):
        cases = {
            "missing": lambda r: r["server"].pop("self_cpu"),
            "value without availability": lambda r: r["server"]["self_cpu"].update(available=False),
            "unavailable without reason": lambda r: r["server"].update(self_cpu=unavailable("ns", "", CPU_SOURCE)),
            "no source": lambda r: r["client"]["self_cpu"].update(source=""),
            "negative": lambda r: r["client"]["self_cpu"].update(value=-1),
            "float": lambda r: r["client"]["self_cpu"].update(value=1.5),
            "wrong unit": lambda r: r["client"]["self_cpu"].update(unit="s"),
        }
        for name, edit in cases.items():
            record = observation()
            edit(record)
            with self.subTest(name), self.assertRaisesRegex(ValueError, "metric|self_cpu"):
                driver.check_observation(record)

    def test_both_representations_of_a_reading_agree(self):
        cases = {
            "rss alias": lambda r: r["server"].update(rss_kb_end=2000),
            "cpu seconds": lambda r: r["server"].update(window_cpu_s=1.0),
            "client cpu seconds": lambda r: r["client"].update(window_cpu_s=31.0),
            "non-string source": lambda r: r["server"]["self_cpu"].update(source=["getrusage"]),
        }
        for name, edit in cases.items():
            record = observation()
            edit(record)
            with self.subTest(name), self.assertRaisesRegex(ValueError, "alias|window_cpu_s|metric"):
                driver.check_observation(record)
        # Go's Duration.Seconds() of the same nanoseconds is the same reading.
        record = observation()
        record["server"]["self_cpu"]["value"] = 123_456_789_123
        record["server"]["window_cpu_s"] = 123_456_789_123 / 1e9
        driver.check_observation(record)

    def test_unavailable_cpu_is_not_window_evidence(self):
        """The producer marks only a negative CPU interval unavailable; window_cpu_s is a
        required positive reading of that same interval, so no record can carry both."""
        for platform in ("linux-amd64", "darwin-arm64"):
            for role in ("server", "client"):
                for seconds in (60.0, -0.5):
                    record = observation("stream" if platform == "darwin-arm64" else "stream-gso-on", platform=platform)
                    record[role]["self_cpu"] = unavailable("ns", "negative CPU interval", CPU_SOURCE)
                    record[role]["window_cpu_s"] = seconds
                    with self.subTest(platform=platform, role=role, seconds=seconds), \
                            self.assertRaisesRegex(ValueError, "self_cpu is unavailable"):
                        driver.check_observation(record)

    def test_useful_bytes_metric_matches_the_flows(self):
        record = observation("mixed-bulk")
        record["client"]["useful_bytes"]["value"] += 1
        with self.assertRaisesRegex(ValueError, "useful"):
            driver.check_observation(record)

    def test_rss_units_and_normalization(self):
        for platform, unit, scale in (("linux-amd64", "kB", 1024), ("darwin-arm64", "bytes", 1)):
            cell = driver.PROFILES[platform]["cells"]
            record = observation(next(iter(cell)), platform=platform)
            driver.check_observation(record)
            self.assertEqual(record["server"]["peak_rss_end"]["bytes"], record["server"]["peak_rss_end"]["value"] * scale)
            for edit in (lambda r: r["server"]["peak_rss_end"].update(bytes=r["server"]["peak_rss_end"]["bytes"] + 1),
                         lambda r: r["server"]["peak_rss_end"].update(unit="bytes" if unit == "kB" else "kB")):
                record = observation(next(iter(cell)), platform=platform)
                edit(record)
                with self.subTest(platform=platform), self.assertRaisesRegex(ValueError, "RSS"):
                    driver.check_observation(record)

    def test_c1_sources_are_the_profile_collectors(self):
        def first_cell(platform):
            return next(iter(driver.PROFILES[platform]["cells"]))
        for platform in ("linux-amd64", "darwin-arm64"):
            for controller in ("reno", "bbrv3"):
                driver.check_observation(observation(first_cell(platform), platform=platform, controller=controller))

        def rejects(record, field, expected):
            with self.assertRaisesRegex(ValueError, f"{field}: source must be {re.escape(repr(expected))}"):
                driver.check_observation(record)

        # Each profile names its own RSS collector; the other profile's is no reading here.
        foreign = {"linux-amd64": RSS_SOURCE["darwin-arm64"], "darwin-arm64": RSS_SOURCE["linux-amd64"]}
        for platform, other in foreign.items():
            for field in ("peak_rss_at_sample", "peak_rss_end"):
                record = observation(first_cell(platform), platform=platform)
                record["server"][field]["source"] = other
                with self.subTest(platform=platform, field=field):
                    rejects(record, field, RSS_SOURCE[platform])
        fields = {
            "server self_cpu": (lambda r: r["server"]["self_cpu"], "self_cpu", CPU_SOURCE),
            "client self_cpu": (lambda r: r["client"]["self_cpu"], "self_cpu", CPU_SOURCE),
            "packets_lost_metric": (lambda r: r["server"]["connections"][0]["packets_lost_metric"], "packets_lost_metric", LOST_SOURCE),
            "useful_bytes": (lambda r: r["client"]["useful_bytes"], "useful_bytes", USEFUL_SOURCE),
        }
        for platform in ("linux-amd64", "darwin-arm64"):
            # BBR's loss metric is unavailable, and is pinned all the same.
            for controller in ("reno", "bbrv3"):
                for name, (get, field, expected) in fields.items():
                    record = observation(first_cell(platform), platform=platform, controller=controller)
                    get(record)["source"] = "fixture producer"
                    with self.subTest(platform=platform, controller=controller, metric=name):
                        rejects(record, field, expected)
            for role in ("server", "client"):
                record = observation(first_cell(platform), platform=platform)
                record[role]["self_cpu"] = unavailable("ns", "negative CPU interval", "fixture producer")
                with self.subTest(platform=platform, unavailable=role):
                    rejects(record, "self_cpu", CPU_SOURCE)

    def test_generic_metric_check_keeps_consumer_sources(self):
        """Consumers with their own producers pin their own sources; the shared check does not."""
        self.assertEqual(driver.check_metric("relay_cpu", metric(5, "ns", "a consumer-owned producer"), "ns"), 5)
        self.assertIsNone(driver.check_metric("relay_cpu", unavailable("ns", "not sampled", "another producer"), "ns"))


class ProducerSourceTests(unittest.TestCase):
    """The readback's expected sources are the named constants the Go producers emit."""

    ROOT = Path(__file__).resolve().parents[2]

    def go_const(self, file, name):
        found = re.findall(rf'^const {name} = ("(?:[^"\\]|\\.)*")$', (self.ROOT / file).read_text(), re.M)
        self.assertEqual(len(found), 1, f"{file} declares const {name} once")
        return json.loads(found[0])

    def test_readback_expects_what_the_producers_emit(self):
        common = {"self_cpu": "ordinaryCostCPUSource", "packets_lost_metric": "ordinaryCostLostSource",
                  "useful_bytes": "ordinaryCostUsefulSource"}
        for platform, file in (("linux-amd64", "ordinary_cost_linux_test.go"), ("darwin-arm64", "ordinary_cost_darwin_test.go")):
            expected = {field: self.go_const("ordinary_cost_test.go", name) for field, name in common.items()}
            expected["peak_rss"] = self.go_const(file, "ordinaryCostRSSSource")
            with self.subTest(platform=platform):
                self.assertEqual(driver.PROFILES[platform]["sources"], expected)


class NativeRecordTests(unittest.TestCase):
    def test_native_observation_is_valid(self):
        for cell in driver.NATIVE_CELLS:
            for profile in ("unregistered", "opted-in"):
                if cell == "mixed-bulk" and profile == "opted-in":
                    continue
                for controller in ("reno", "bbrv3"):
                    driver.check_observation(observation(cell, profile, platform="darwin-arm64", controller=controller))

    def test_missing_or_mismatched_native_identity_fails(self):
        for role in ("server", "client"):
            for edit in (lambda r: r[role].pop("platform"),
                         lambda r: r[role].update(platform=identity("linux-amd64")),
                         lambda r: r[role]["platform"].update(goarch="amd64")):
                record = observation("stream", platform="darwin-arm64")
                edit(record)
                with self.subTest(role=role), self.assertRaisesRegex(ValueError, "identity"):
                    driver.check_observation(record)
        record = observation()
        record["server"].pop("platform")
        with self.assertRaisesRegex(ValueError, "identity"):
            driver.check_observation(record)

    def test_native_never_claims_linux_counters_or_negotiation(self):
        cases = {
            "gso": lambda r: r["server"].update(gso_capable=True),
            "advertised": lambda r: r["server"].update(multipath_advertised=True),
            "legacy rss": lambda r: r["server"].update(rss_kb_end=1000),
            "quiet host": lambda r: r.update(host_activity={"status": "quiet"}),
        }
        for name, edit in cases.items():
            record = observation("stream", "opted-in", platform="darwin-arm64")
            edit(record)
            with self.subTest(name), self.assertRaises(ValueError):
                driver.check_observation(record)

    def test_private_grant_receipt_cannot_claim_negotiation(self):
        cases = {
            "connection": lambda r: r["server"]["connections"][0].update(multipath_negotiated=True),
            "connection unstated": lambda r: r["server"]["connections"][0].pop("multipath_negotiated"),
            "flow": lambda r: r["client"]["flows"][0].update(multipath_negotiated=True),
            "flow unstated": lambda r: r["client"]["flows"][0].pop("multipath_negotiated"),
            "paths": lambda r: r["client"]["flows"][0].update(paths=["live", "live"]),
        }
        for name, edit in cases.items():
            record = observation("stream", "opted-in", platform="darwin-arm64")
            edit(record)
            with self.subTest(name), self.assertRaisesRegex(ValueError, "negotiated"):
                driver.check_observation(record)
        driver.check_observation(observation("mixed-bulk", "opted-in"))

    def test_native_negotiated_mixed_bulk_is_refused_not_replaced(self):
        record = observation("mixed-bulk", "unregistered", platform="darwin-arm64")
        driver.check_observation(record)
        record = observation("mixed-bulk", "opted-in", platform="darwin-arm64")
        with self.assertRaisesRegex(ValueError, "negotiated"):
            driver.check_observation(record)


FIXTURE = Path(__file__).parent / "testdata" / "powermetrics" / "cpu_power.plist"
# The fixture holds two contiguous samples of 1.00025 s. This sampler ran 2.2 s around a
# window from 0.3 s to 1.9 s after launch, so the samples certainly cover it.
COVERAGE = {"launched": 100.0, "stopped": 102.2, "window_start": 100.3, "window_end": 101.9}


class PowermetricsTests(unittest.TestCase):
    """Recorded producer-shaped plist fixtures; no privileged sampling."""

    def test_recorded_records_attribute_both_cluster_kinds(self):
        raw = FIXTURE.read_bytes()
        records, tail = driver.parse_powermetrics(raw)
        self.assertEqual(len(records), 2)
        self.assertEqual(tail, 0)
        activity = driver.cluster_activity(records, COVERAGE)
        self.assertEqual(activity["status"], "observed")
        self.assertEqual(activity["records"], 2)
        by_name = {cluster["name"]: cluster for cluster in activity["clusters"]}
        self.assertEqual({name: c["class"] for name, c in by_name.items()},
                         {"E-Cluster": "efficiency", "P0-Cluster": "performance", "P1-Cluster": "performance"})
        self.assertAlmostEqual(by_name["E-Cluster"]["active_ratio"], 0.25)
        self.assertAlmostEqual(by_name["P0-Cluster"]["active_ratio"], 0.075)

    def test_separator_or_terminator_both_parse_and_a_cut_tail_is_not_evidence(self):
        raw = FIXTURE.read_bytes()
        records, tail = driver.parse_powermetrics(raw.rstrip(b"\0"))
        self.assertEqual((len(records), tail), (2, 0))
        records, tail = driver.parse_powermetrics(raw + raw[:200])
        self.assertEqual(len(records), 4 - 2)
        self.assertEqual(tail, 200)

    def test_malformed_record_fails(self):
        first, second = FIXTURE.read_bytes().split(b"\0")[:2]
        for bad in (first + b"\0<plist><dict><key>x</key></plist>\0" + second + b"\0",
                    b"<?xml version='1.0'?><plist version='1.0'><array/></plist>\0" + second + b"\0"):
            with self.subTest(bad=bad[:20]), self.assertRaisesRegex(ValueError, "powermetrics"):
                driver.parse_powermetrics(bad)
        # Separators alone hold no record, which the adapter classifies as inconclusive.
        records, tail = driver.parse_powermetrics(b"\0\0")
        self.assertEqual((records, tail), ([], 0))
        with self.assertRaises(driver.HostObservationError) as caught:
            driver.cluster_activity(records, COVERAGE)
        self.assertEqual(caught.exception.status, "inconclusive")

    def test_unsupported_or_incomplete_records_are_inconclusive(self):
        records, _ = driver.parse_powermetrics(FIXTURE.read_bytes())

        def edited(edit):
            copied = copy.deepcopy(records)
            edit(copied)
            return copied

        cases = {
            "unknown cluster": edited(lambda r: r[0]["processor"]["clusters"][0].update(name="X-Cluster")),
            "missing idle": edited(lambda r: r[1]["processor"]["clusters"][1].pop("idle_ratio")),
            "idle out of range": edited(lambda r: r[1]["processor"]["clusters"][1].update(idle_ratio=1.5)),
            "no processor": edited(lambda r: r[0].pop("processor")),
            "no elapsed": edited(lambda r: r[0].pop("elapsed_ns")),
            "changed cluster set": edited(lambda r: r[1]["processor"]["clusters"].pop()),
            "absolute sample": edited(lambda r: r[0].update(is_delta=False)),
        }
        for name, case in cases.items():
            with self.subTest(name), self.assertRaises(driver.HostObservationError) as caught:
                driver.cluster_activity(case, COVERAGE)
            self.assertEqual(caught.exception.status, "inconclusive")

    def test_repeated_cluster_name_is_inconclusive(self):
        records, _ = driver.parse_powermetrics(FIXTURE.read_bytes())
        doubled = copy.deepcopy(records)
        for record in doubled:
            clusters = record["processor"]["clusters"]
            clusters.append(copy.deepcopy(clusters[0]))
        with self.assertRaises(driver.HostObservationError) as caught:
            driver.cluster_activity(doubled, COVERAGE)
        self.assertEqual(caught.exception.status, "inconclusive")
        self.assertIn("repeated", str(caught.exception))
        by_name = {c["name"]: c for c in driver.cluster_activity(records, COVERAGE)["clusters"]}
        self.assertAlmostEqual(by_name["E-Cluster"]["active_ratio"], 0.25)

    def test_down_residency_is_not_activity(self):
        records, _ = driver.parse_powermetrics(FIXTURE.read_bytes())
        for record in records:
            record["processor"]["clusters"][0].update(idle_ratio=0.2, down_ratio=0.7)
        activity = driver.cluster_activity(records, COVERAGE)
        self.assertAlmostEqual(activity["clusters"][0]["active_ratio"], 0.1)
        records[1]["processor"]["clusters"][0].update(idle_ratio=0.5, down_ratio=0.6)
        with self.assertRaisesRegex(driver.HostObservationError, "residency"):
            driver.cluster_activity(records, COVERAGE)
        records[1]["processor"]["clusters"][0].pop("down_ratio")
        with self.assertRaisesRegex(driver.HostObservationError, "residency"):
            driver.cluster_activity(records, COVERAGE)

    def test_samples_must_certainly_cover_the_window(self):
        records, _ = driver.parse_powermetrics(FIXTURE.read_bytes())
        cases = {
            # Enough total time, but emitted at launch: the window starts 3 s later.
            "before the window": dict(COVERAGE, stopped=105.0, window_start=103.0, window_end=104.0),
            # The samples could all have finished before the window's end.
            "short of the end": dict(COVERAGE, window_end=102.1),
            # They could have started after the window began.
            "after the start": dict(COVERAGE, window_start=100.1),
            # More elapsed time than the sampler lived.
            "impossible": dict(COVERAGE, stopped=101.0, window_start=100.1, window_end=100.9),
        }
        for name, coverage in cases.items():
            with self.subTest(name), self.assertRaises(driver.HostObservationError) as caught:
                driver.cluster_activity(records, coverage)
            self.assertEqual(caught.exception.status, "inconclusive")

    def run_sampler(self, root, script, window=(0.3, 1.9), lifetime=2.2):
        sampler = driver.HostSampler([sys.executable, "-c", script], root)
        sampler.start()
        launched = sampler.started
        time.sleep(lifetime)
        return sampler.finish(launched + window[0], launched + window[1])

    def test_sampler_route_is_the_owner_installed_wrapper_under_sudo(self):
        wrapper_path = "/usr/local/libexec/quicquic-powermetrics"
        self.assertEqual(driver.powermetrics_command(), ["/usr/bin/sudo", "-n", wrapper_path, "driver-stopped"])
        self.assertEqual(driver.powermetrics_command("bounded"), ["/usr/bin/sudo", "-n", wrapper_path, "bounded"])
        self.assertLessEqual({"driver-stopped", "bounded"}, set(powermetrics_wrapper.MODES))
        # The driver's bounded wait covers the wrapper's own grace before SIGKILL.
        self.assertLess(powermetrics_wrapper.STOP_GRACE_S + 1, driver.SAMPLER_STOP_S)

    def test_killed_driver_leaves_no_sampler_running(self):
        """The real wrapper with a sampler that ignores SIGTERM, under a driver killed by
        SIGKILL while a role it launched afterwards is still alive: the role must not hold
        the sampler's stdin open, so the wrapper sees EOF and reaps the sampler."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake = fake_powermetrics(root, payload=FIXTURE.read_bytes(), ignore_term=True, linger_s=60)
            command = wrapper_command(fake, ["driver-stopped"], "w.STOP_GRACE_S = 0.3")
            bootstrap = textwrap.dedent("""
                import json, subprocess, sys, time
                from pathlib import Path
                sys.path.insert(0, sys.argv[2])
                import ordinary_cost as driver
                root = Path(sys.argv[1])
                sampler = driver.HostSampler(json.loads(sys.argv[3]), root)
                sampler.start()
                role = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
                (root / "pids.json").write_text(json.dumps({"wrapper": sampler.process.pid, "role": role.pid}))
                time.sleep(60)
            """)
            driver_process = subprocess.Popen([sys.executable, "-c", bootstrap, str(root), str(Path(driver.__file__).parent),
                                               json.dumps(command)])
            self.addCleanup(driver_process.wait)
            self.addCleanup(lambda: driver_process.poll() is None and driver_process.kill())
            deadline = time.monotonic() + 15
            while not ((root / "pids.json").exists() and (root / "invoked.json").exists()):
                self.assertLess(time.monotonic(), deadline, "the driver did not start its sampler and role")
                time.sleep(0.05)
            time.sleep(0.1)  # let both files finish writing
            pids = json.loads((root / "pids.json").read_text())
            sampler_pid = json.loads((root / "invoked.json").read_text())["pid"]
            self.addCleanup(lambda: alive(pids["role"]) and os.kill(pids["role"], signal.SIGKILL))
            self.addCleanup(lambda: alive(pids["wrapper"]) and os.kill(pids["wrapper"], signal.SIGKILL))
            self.addCleanup(lambda: alive(sampler_pid) and os.kill(sampler_pid, signal.SIGKILL))
            driver_process.kill()
            driver_process.wait()
            self.assertTrue(wait_gone(sampler_pid), "the sampler outlived its killed driver")
            self.assertTrue(wait_gone(pids["wrapper"]), "the wrapper outlived its killed driver")
            self.assertTrue(alive(pids["role"]), "the role was still running, holding whatever it inherited")

    def test_window_bounds_bracket_the_clock_conversion(self):
        # The driver is preempted for 0.5 s between its two monotonic reads.
        readings = iter((10.0, 10.5))
        start, end = driver.window_bounds(1002 * 10**9, 1, 1, monotonic=lambda: next(readings),
                                          wall_ns=lambda: 1000 * 10**9)
        self.assertEqual((start, end), (13.0, 14.5))
        # 2.0005 s of samples ending at 14.2005 at the latest: past an estimate taken from
        # the first read alone (14.0), short of the latest possible window end.
        records, _ = driver.parse_powermetrics(FIXTURE.read_bytes())
        coverage = {"launched": 12.2, "stopped": 14.3, "window_start": start}
        self.assertEqual(driver.cluster_activity(records, dict(coverage, window_end=14.0))["status"], "observed")
        with self.assertRaises(driver.HostObservationError) as caught:
            driver.cluster_activity(records, dict(coverage, window_end=end))
        self.assertEqual(caught.exception.status, "inconclusive")

    def test_missing_grant_is_unavailable_never_quiet(self):
        """sudo -n refuses at once rather than prompting; the refusal is the record."""
        with tempfile.TemporaryDirectory() as temporary:
            activity = self.run_sampler(Path(temporary),
                "import sys; sys.stderr.write('sudo: a password is required\\n'); sys.exit(1)")
        self.assertEqual(activity["status"], "unavailable")
        self.assertIn("a password is required", activity["reason"])
        self.assertEqual(activity["exit"], 1)
        self.assertTrue(activity["joined"])

    def test_sampler_output_is_preserved_and_parsed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = textwrap.dedent(f"""
                import os, signal, sys
                signal.signal(signal.SIGTERM, signal.SIG_IGN)  # only standard input stops it
                print(os.getsid(0) == os.getpid(), file=sys.stderr, flush=True)
                sys.stdout.buffer.write(open({str(FIXTURE)!r}, 'rb').read()); sys.stdout.flush()
                sys.stdin.read()
            """)
            activity = self.run_sampler(root, script)
            self.assertEqual(activity["status"], "observed", activity)
            self.assertEqual((root / "host.log").read_text().strip(), "True", "the sampler leads its own session")
            self.assertEqual((root / "host.plist").read_bytes(), FIXTURE.read_bytes())
            self.assertEqual(activity["raw_sha256"], hashlib.sha256(FIXTURE.read_bytes()).hexdigest())
            self.assertTrue(activity["joined"])

    def test_missing_sampler_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temporary:
            sampler = driver.HostSampler([str(Path(temporary) / "no-such-powermetrics")], Path(temporary))
            sampler.start()
            activity = sampler.finish(0, 0)
        self.assertEqual(activity["status"], "unavailable")
        self.assertIn("never launched", activity["reason"])
        self.assertFalse(activity["joined"])

    def test_sampler_that_ends_early_is_incomplete(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            activity = self.run_sampler(root, f"import sys; sys.stdout.buffer.write(open({str(FIXTURE)!r}, 'rb').read())")
        self.assertEqual(activity["status"], "inconclusive")
        self.assertIn("before the window ended", activity["reason"])

    def test_interrupted_stop_has_already_closed_the_samplers_stdin(self):
        """Standard input closes before the wait, so a failed wait still stops the sampler."""
        with tempfile.TemporaryDirectory() as temporary:
            sampler = driver.HostSampler([sys.executable, "-c", "import sys; sys.stdin.read(); sys.exit(0)"],
                                         Path(temporary))
            sampler.start()
            process, real_wait = sampler.process, sampler.process.wait

            def interrupted(timeout=None):
                if timeout is not None:
                    raise KeyboardInterrupt("SIGTERM")
                return real_wait()

            with mock.patch.object(process, "wait", side_effect=interrupted), self.assertRaises(KeyboardInterrupt):
                sampler.finish(0, 0)
            self.assertTrue(process.stdin.closed)
            self.assertEqual(real_wait(timeout=10), 0, "the sampler stopped on its own")

    def test_operator_signal_waits_until_the_sampler_is_reaped(self):
        with tempfile.TemporaryDirectory() as temporary:
            sampler = driver.HostSampler([sys.executable, "-c", "import sys, time; sys.stdin.read(); time.sleep(0.3)"],
                                         Path(temporary))
            sampler.start()
            process, real_wait = sampler.process, sampler.process.wait

            def signaled_wait(timeout=None):
                # A SIGINT while the driver waits on the stopping sampler.
                os.kill(os.getpid(), signal.SIGINT)
                return real_wait(timeout)

            with mock.patch.object(process, "wait", side_effect=signaled_wait), self.assertRaises(KeyboardInterrupt):
                sampler.stop()
            self.assertEqual(process.returncode, 0, "the interrupt was delivered after the sampler was reaped")
            with self.assertRaises(ProcessLookupError):
                os.kill(process.pid, 0)

    def test_coverage_bounds_bracket_the_sampler_process(self):
        """Launch is read before the child can exist, and stop after it is reaped, so
        neither bound can fall inside the child's lifetime."""
        marks, real_popen = {}, subprocess.Popen

        class Process(real_popen):
            def __init__(self, *args, **kwargs):
                marks["entered"] = time.monotonic()
                super().__init__(*args, **kwargs)
                time.sleep(0.2)  # the parent is descheduled while the child samples

            def wait(self, timeout=None):
                code = super().wait(timeout)
                marks["reaped"] = time.monotonic()
                return code

        seen = {}

        def capture(records, coverage):
            seen.update(coverage)
            return {"status": "observed"}

        script = textwrap.dedent(f"""
            import signal, sys, time
            sys.stdout.buffer.write(open({str(FIXTURE)!r}, 'rb').read()); sys.stdout.flush()
            sys.stdin.read()
            time.sleep(0.2)  # the sampler takes a moment to stop after its stdin closes
        """)
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(driver.subprocess, "Popen", Process), \
                mock.patch.object(driver, "cluster_activity", side_effect=capture):
            sampler = driver.HostSampler([sys.executable, "-c", script], Path(temporary))
            sampler.start()
            self.assertLessEqual(sampler.started, marks["entered"])
            time.sleep(0.3)
            activity = sampler.finish(sampler.started, sampler.started + 0.1)
        self.assertEqual(activity["status"], "observed", activity)
        self.assertGreaterEqual(seen["stopped"], marks["reaped"])

    def test_sampler_not_stopped_by_its_stdin_is_unavailable_and_never_signaled(self):
        """The driver cannot signal the privileged sampler, so a sampler still running after
        the bounded wait is left alone and recorded unavailable."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = textwrap.dedent(f"""
                import signal, time
                from pathlib import Path
                def note(number, frame):
                    with (Path({str(root)!r}) / "signals.txt").open("a") as file:
                        file.write(str(number) + "\\n")
                for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                    signal.signal(number, note)
                time.sleep(60)  # never reads standard input
            """)
            with mock.patch.object(driver, "SAMPLER_STOP_S", 0.3):
                sampler = driver.HostSampler([sys.executable, "-c", script], root)
                sampler.start()
                self.addCleanup(lambda: sampler.process.poll() is None and (sampler.process.kill(), sampler.process.wait()))
                launched = sampler.started
                time.sleep(2.2)
                activity = sampler.finish(launched + 0.3, launched + 1.9)
            self.assertEqual(activity["status"], "unavailable")
            self.assertIn("not confirmed stopped", activity["reason"])
            self.assertFalse(activity["joined"])
            self.assertIsNone(sampler.process.poll(), "the sampler was left running")
            self.assertFalse((root / "signals.txt").exists(), "the driver sent the sampler no signal")


class NativeExecutionTests(unittest.TestCase):
    invoke = ExecutionTests.invoke
    exercise_sigterm_during_roles = ExecutionTests.exercise_sigterm_during_roles

    def test_native_smoke_records_without_a_verdict(self):
        for cell in driver.NATIVE_CELLS:
            for controller in ("reno", "bbrv3"):
                with self.subTest(cell=cell, controller=controller), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    code, summary, processes = self.invoke(root, ("--platform-profile", "darwin-arm64", "--smoke-cell", cell,
                                                                  "--controller", controller), platform="darwin-arm64")
                    self.assertEqual(code, 0, summary.get("error"))
                    self.assertFalse(summary["judged"])
                    self.assertNotIn("diagnostic", summary)
                    records = [json.loads(line) for line in (root / "output" / "smoke.jsonl").read_text().splitlines()]
                    expected = ["unregistered"] if cell == "mixed-bulk" else ["unregistered", "opted-in"]
                    self.assertEqual([record["profile"] for record in records], expected)
                    self.assertEqual(len(processes), 2 * len(expected))
                    if cell == "mixed-bulk":
                        self.assertIn("Q2", summary["not_run"]["opted-in"])
                    for record in records:
                        self.assertEqual(record["host_activity"]["status"], "unavailable")
                        self.assertNotIn("contaminated", record)
                    identity_record = json.loads((root / "output" / "identity.json").read_text())
                    self.assertEqual(identity_record["platform_profile"], "darwin-arm64")
                    self.assertNotIn("server_cpus", identity_record)
                    with self.assertRaises(ValueError):
                        driver.check_accounting(records)

    def test_native_smoke_fails_on_a_failed_workload(self):
        def write_error(record):
            if record["profile"] == driver.OPTED_IN:
                record["server"]["write_errors"] = 1

        for cell, edit, failure in (("stream", write_error, "opted-in: 1 write errors"),
                                    ("mixed-bulk", lambda record: idle(record, 2),
                                     "unregistered: background delivered no useful bytes")):
            with self.subTest(cell=cell), tempfile.TemporaryDirectory() as temporary:
                code, summary, _ = self.invoke(Path(temporary), ("--platform-profile", "darwin-arm64", "--smoke-cell", cell),
                                               edit=edit, platform="darwin-arm64")
                self.assertEqual(code, 1, summary)
                self.assertFalse(summary["passed"])
                self.assertFalse(summary["judged"])
                self.assertEqual(summary["workload_failures"], [failure])

    def test_unjudged_pressure_smoke_fails_without_a_reset(self):
        def silent(record):
            if record["profile"] == driver.OPTED_IN:
                record["client"]["flood"]["resets"] = 0

        failure = "opted-in: 600000 pressure packets drew no stateless reset"
        with tempfile.TemporaryDirectory() as temporary:
            code, summary, _ = self.invoke(Path(temporary), ("--platform-profile", "darwin-arm64",
                                                             "--smoke-cell", "stateless-pressure"),
                                           edit=silent, platform="darwin-arm64")
        self.assertEqual(code, 1, summary)
        self.assertFalse(summary["judged"])
        self.assertEqual(summary["workload_failures"], [failure])
        # Still a valid record, so a judged Reno pair keeps reporting its reset share.
        record = observation("stateless-pressure", "opted-in")
        silent(record)
        driver.check_observation(record)
        self.assertEqual(driver.workload_failures(record), [failure])

    def test_native_campaign_launches_nothing(self):
        for extra in ((), ("--revalidate-cell", "stream", "--cause", "x")):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                    self.invoke(root, ("--platform-profile", "darwin-arm64", *extra), platform="darwin-arm64")
                self.assertEqual(caught.exception.code, 2)
                self.assertFalse((root / "output").exists())

    def test_wrong_host_for_profile_fails_before_launch(self):
        with tempfile.TemporaryDirectory() as temporary, self.assertRaisesRegex(RuntimeError, "Darwin arm64"):
            self.invoke(Path(temporary), ("--platform-profile", "darwin-arm64", "--smoke-cell", "stream"))
        with tempfile.TemporaryDirectory() as temporary, self.assertRaisesRegex(RuntimeError, "Linux amd64"):
            self.invoke(Path(temporary), ("--smoke-cell", "stream-gso-on"), platform="darwin-arm64")

    def test_native_sampler_is_launched_and_joined_per_observation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            code, summary, _ = self.invoke(root, ("--platform-profile", "darwin-arm64", "--smoke-cell", "stream",
                                                  "--host-sampler", "powermetrics"), platform="darwin-arm64", role_s=0.5,
                                           sampler=[sys.executable, "-c", "import sys; sys.stderr.write('must be invoked as the superuser'); sys.exit(1)"])
            self.assertEqual(code, 0, summary.get("error"))
            records = [json.loads(line) for line in (root / "output" / "smoke.jsonl").read_text().splitlines()]
            for record in records:
                self.assertEqual(record["host_activity"]["status"], "unavailable")
                self.assertTrue(record["host_activity"]["joined"])
                self.assertIn("superuser", record["host_activity"]["reason"])

    def test_interrupted_sampler_keeps_the_attempt_facts(self):
        def interrupted(sampler, *_):
            sampler.stop()  # the real child is still reaped
            raise KeyboardInterrupt("SIGTERM")

        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(driver.HostSampler, "finish", autospec=True, side_effect=interrupted):
            code, summary, processes = self.invoke(Path(temporary), ("--platform-profile", "darwin-arm64", "--smoke-cell", "stream",
                                                                     "--host-sampler", "powermetrics"), platform="darwin-arm64",
                                                   sampler=[sys.executable, "-c", "pass"])
        self.assertEqual(code, 1)
        attempt = summary["attempts"][0]
        self.assertEqual(attempt["status"], "failed")
        self.assertIn("SIGTERM", attempt["error"])
        self.assertEqual(attempt["platform_profile"], "darwin-arm64")
        self.assertEqual(set(attempt["exit"]), {"server", "client"})
        self.assertIn("process_cpu_s", attempt)
        self.assertTrue(all(process.returncode is not None for process in processes))

    def test_interrupt_before_sampler_stop_is_deferred_until_it_is_reaped(self):
        real_stop, stopped = driver.HostSampler.stop, []

        def signaled(sampler):
            # A SIGTERM at the teardown boundary, before the sampler's own shutdown begins.
            os.kill(os.getpid(), signal.SIGTERM)
            stopped.append(sampler)
            return real_stop(sampler)

        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(driver.HostSampler, "stop", autospec=True, side_effect=signaled):
            code, summary, processes = self.invoke(Path(temporary), ("--platform-profile", "darwin-arm64", "--smoke-cell", "stream",
                                                                     "--host-sampler", "powermetrics"), platform="darwin-arm64",
                                                   sampler=[sys.executable, "-c", "import sys; sys.stdin.read()"])
        self.assertEqual(code, 1, summary)
        attempt = summary["attempts"][0]
        self.assertEqual(attempt["status"], "failed")
        self.assertIn("SIGTERM", attempt["error"])
        self.assertEqual(set(attempt["exit"]), {"server", "client"})
        self.assertIn("occupied_s", attempt)
        self.assertEqual(len(stopped), 1)
        self.assertIsNotNone(stopped[0].process.returncode, "the sampler was reaped before the interrupt was honored")
        with self.assertRaises(ProcessLookupError):
            os.kill(stopped[0].process.pid, 0)
        self.assertTrue(all(process.returncode is not None for process in processes))

    def test_interrupt_gate_keeps_inherited_ignores_for_children(self):
        previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            with driver.DeferredInterrupts():
                self.assertIs(signal.getsignal(signal.SIGINT), signal.SIG_IGN)
                child = subprocess.run([sys.executable, "-c",
                                        "import signal; print(signal.getsignal(signal.SIGINT) is signal.SIG_IGN)"],
                                       capture_output=True, text=True, check=True)
            self.assertEqual(child.stdout.strip(), "True")
            self.assertIs(signal.getsignal(signal.SIGINT), signal.SIG_IGN)
        finally:
            signal.signal(signal.SIGINT, previous)

    def test_interrupt_gate_is_ready_before_its_handler_can_run(self):
        real_signal, before = signal.signal, {n: signal.getsignal(n) for n in driver.DeferredInterrupts.SIGNALS}

        def delivered_at_install(number, handler):
            previous = real_signal(number, handler)
            if getattr(handler, "__self__", None).__class__ is driver.DeferredInterrupts and number == signal.SIGINT:
                handler(number, None)  # a SIGINT the instant the gate's handler is installed
            return previous

        with mock.patch.object(driver.signal, "signal", side_effect=delivered_at_install), \
                self.assertRaises(KeyboardInterrupt):
            with driver.DeferredInterrupts():
                pass  # nothing is interruptible here; the interrupt is honored on exit
        self.assertEqual({n: signal.getsignal(n) for n in before}, before)

    def test_output_parsing_is_cancellable_after_every_child_is_reaped(self):
        real_finish, continued = driver.HostSampler.finish, []

        def signaled(sampler, *args):
            self.assertIsNotNone(sampler.process.returncode, "the sampler is reaped before parsing")
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(1)  # an honored interrupt ends this wait
            continued.append(True)
            return real_finish(sampler, *args)

        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(driver.HostSampler, "finish", autospec=True, side_effect=signaled):
            code, summary, _ = self.invoke(Path(temporary), ("--platform-profile", "darwin-arm64", "--smoke-cell", "stream",
                                                             "--host-sampler", "powermetrics"), platform="darwin-arm64",
                                           sampler=[sys.executable, "-c", "import sys; sys.stdin.read()"])
        self.assertEqual(code, 1)
        self.assertIn("SIGTERM", summary["attempts"][0]["error"])
        self.assertEqual(continued, [])

    def test_sigterm_reaps_roles_and_sampler(self):
        self.exercise_sigterm_during_roles(native=True)


def path_state(wire_id, lifecycle="live", local_use="active", primary=False, validated=True, tuple_generation=0):
    return {"wire_id": wire_id, "tuple_generation": tuple_generation, "lifecycle": lifecycle,
            "local_use": local_use, "primary": primary, "validated": validated}


def lifecycle_record(controller="reno", retired="closed", heap=(4_000_000, 4_100_000, 4_010_000)):
    """A producer-shaped lifecycle-memory record, as ordinary_cost_lifecycle_test.go writes it."""
    states = (path_state(0, primary=True), path_state(1, local_use="backup", tuple_generation=1),
              path_state(1, lifecycle=retired, local_use="backup", tuple_generation=1))
    samples = []
    for phase, state, value in zip(driver.LIFECYCLE_PHASES, states, heap):
        samples.append({
            "phase": phase, "role": "client", "path_id": state["wire_id"], "multipath_negotiated": True,
            "baseline": None if phase == "negotiated-idle" else "negotiated-idle",
            "state_before": dict(state), "state_after": dict(state),
            "go_heap_live": metric(value, "bytes", driver.LIFECYCLE_BOUNDARY_SOURCES["go_heap_live"]),
            "peak_rss": metric(20_000, "kB", "/proc/self/status VmHWM", bytes=20_000 * 1024),
        })
    joins = driver.LIFECYCLE_BOUNDARY_SOURCES["grant_joins"]
    return {
        "workload": driver.LIFECYCLE, "controller": controller, "platform_profile": "linux-amd64",
        "retired_lifecycle": retired, "exit": {"server": 0, "client": 0}, "status": "succeeded",
        "server": {"format": driver.LIFECYCLE_FORMAT, "role": "server", "controller": controller, "go": driver.GO_VERSION, "platform": identity("linux-amd64"),
                   "multipath_negotiated": True, "peer_closed": True, "close_cause": "Application error 0x0 (remote)",
                   "grant_joins": {"origin": True}, "grant_join_source": joins},
        "client": {"format": driver.LIFECYCLE_FORMAT, "role": "client", "controller": controller, "go": driver.GO_VERSION, "platform": identity("linux-amd64"),
                   "retired_lifecycle": retired, "multipath_negotiated": True, "samples": samples,
                   "transport_detachment": {"transport": "backup", "detached": True,
                                            "source": driver.LIFECYCLE_BOUNDARY_SOURCES["transport_detachment"]},
                   "grant_joins": {"origin": True, "backup": True}, "grant_join_source": joins},
    }


class LifecycleRecordTests(unittest.TestCase):
    def rejects(self, edit, message):
        record = lifecycle_record()
        edit(record)
        with self.assertRaisesRegex(ValueError, message):
            driver.check_lifecycle(record)

    def sample(self, record, phase):
        return next(sample for sample in record["client"]["samples"] if sample["phase"] == phase)

    def test_negotiated_lifecycle_record_is_valid(self):
        for controller in ("reno", "bbrv3"):
            for retired in driver.LIFECYCLE_RETIRED:
                with self.subTest(controller=controller, retired=retired):
                    driver.check_lifecycle(lifecycle_record(controller, retired))

    def test_unnegotiated_or_ordinary_backup_control_fails(self):
        def unnegotiated(record):
            self.sample(record, "validated-backup")["multipath_negotiated"] = False
        self.rejects(unnegotiated, "unnegotiated connection is no lifecycle or backup control")
        def ordinary_client(record):
            record["client"]["multipath_negotiated"] = False
        self.rejects(ordinary_client, "unnegotiated")
        def ordinary_baseline(record):
            self.sample(record, "validated-backup")["baseline"] = "ordinary-idle"
        self.rejects(ordinary_baseline, "matched comparison is negotiated-idle")
        def baseline_of_baseline(record):
            self.sample(record, "negotiated-idle")["baseline"] = "negotiated-idle"
        self.rejects(baseline_of_baseline, "matched comparison is None")
        def no_baseline(record):
            del self.sample(record, "retired")["baseline"]
        self.rejects(no_baseline, "matched comparison")

    def test_requested_or_detached_state_is_not_retirement(self):
        for lifecycle in ("retiring", "live", "retained"):
            with self.subTest(lifecycle=lifecycle):
                def unobserved(record):
                    sample = self.sample(record, "retired")
                    for field in ("state_before", "state_after"):
                        sample[field]["lifecycle"] = lifecycle
                self.rejects(unobserved, f"needs the backup path closed, not path 1 {lifecycle}")

    def test_stale_sample_fails(self):
        def stale(record):
            self.sample(record, "retired")["state_after"]["lifecycle"] = "retained"
        self.rejects(stale, "stale sample")
        def migrated(record):
            self.sample(record, "validated-backup")["state_after"]["tuple_generation"] = 2
        self.rejects(migrated, "stale sample")

    def test_phase_path_and_role_labels(self):
        def reordered(record):
            samples = record["client"]["samples"]
            samples[0], samples[1] = samples[1], samples[0]
        self.rejects(reordered, "exactly")
        def fourth(record):
            record["client"]["samples"].append(copy.deepcopy(record["client"]["samples"][2]))
        self.rejects(fourth, "exactly")
        def server_sampled(record):
            self.sample(record, "validated-backup")["role"] = "server"
        self.rejects(server_sampled, "not the client role")
        def other_path(record):
            sample = self.sample(record, "retired")
            sample["path_id"] = 2
            for field in ("state_before", "state_after"):
                sample[field]["wire_id"] = 2
        self.rejects(other_path, "backup's path ID")
        def mislabeled_path(record):
            self.sample(record, "validated-backup")["path_id"] = 2
        self.rejects(mislabeled_path, "not of the sampled path 2")
        def idle_backup(record):
            sample = self.sample(record, "validated-backup")
            for field in ("state_before", "state_after"):
                sample[field].update(local_use="active", primary=True)
        self.rejects(idle_backup, "needs a live, validated backup")
        def unvalidated_idle(record):
            sample = self.sample(record, "negotiated-idle")
            for field in ("state_before", "state_after"):
                sample[field].update(lifecycle="validating", validated=False)
        self.rejects(unvalidated_idle, "needs live, validated, primary path zero")
        def swapped_role(record):
            record["server"]["role"] = "client"
        self.rejects(swapped_role, "server: role")

    def test_heap_and_rss_readings(self):
        def no_heap(record):
            self.sample(record, "negotiated-idle")["go_heap_live"] = unavailable("bytes", "no runtime metric")
        self.rejects(no_heap, "no live Go-heap reading")
        def other_method(record):
            self.sample(record, "retired")["go_heap_live"]["source"] = "runtime.MemStats.HeapInuse"
        self.rejects(other_method, "no live Go-heap reading")
        def unnormalized(record):
            self.sample(record, "retired")["peak_rss"]["bytes"] = 20_000
        self.rejects(unnormalized, "do not normalize")
        def darwin_unit(record):
            self.sample(record, "retired")["peak_rss"] = metric(20_000, "bytes", bytes=20_000)
        self.rejects(darwin_unit, "RSS unit must be kB")
        def foreign_collector(record):
            self.sample(record, "validated-backup")["peak_rss"]["source"] = "getrusage(RUSAGE_SELF).ru_maxrss"
        self.rejects(foreign_collector, re.escape("validated-backup peak_rss: source must be '/proc/self/status VmHWM'"))

    def test_detachment_and_grant_joins_are_separate(self):
        def unjoined(record):
            record["client"]["grant_joins"]["backup"] = False
        self.rejects(unjoined, "every grant must join")
        def undetached(record):
            record["client"]["transport_detachment"]["detached"] = False
        self.rejects(undetached, "did not detach")
        def detachment_as_join(record):
            record["client"]["grant_join_source"] = driver.LIFECYCLE_BOUNDARY_SOURCES["transport_detachment"]
        self.rejects(detachment_as_join, "grant joins come from WaitMultipathIOStoppedV1")
        def server_unjoined(record):
            record["server"]["grant_joins"] = {}
        self.rejects(server_unjoined, "server: its grant did not join")
        def server_timed_out(record):
            record["server"]["peer_closed"] = False
        self.rejects(server_timed_out, "without the client's close")

    def test_run_identity_and_qualifying_state(self):
        def unknown_state(record):
            record["retired_lifecycle"] = "retiring"
        self.rejects(unknown_state, "retained or closed")
        def client_state(record):
            record["client"]["retired_lifecycle"] = "retained"
        self.rejects(client_state, "not the run's")
        def controller(record):
            record["client"]["controller"] = "bbrv3"
        self.rejects(controller, "client: role, controller or toolchain")
        for role in ("server", "client"):
            def unobserved(record):
                record[role]["controller"] = ""
            self.rejects(unobserved, f"{role}: role, controller or toolchain")
        def platform(record):
            record["client"]["platform"] = identity("darwin-arm64")
        self.rejects(platform, "native identity")
        for role in ("server", "client"):
            def unversioned(record):
                del record[role]["format"]
            self.rejects(unversioned, f"{role}: unsupported lifecycle record format")
            def revised(record):
                record[role]["format"] = "mp-mac-c2-lifecycle-memory/2"
            self.rejects(revised, "unsupported lifecycle record format")
            def failed(record):
                record["exit"][role] = 1
            self.rejects(failed, "both roles must exit 0")

    def test_json_types_stay_apart(self):
        for label, edit in (
                ("both roles must exit 0", lambda r: r["exit"].update(client=False)),
                ("every grant must join", lambda r: r["client"]["grant_joins"].update(backup=1)),
                ("did not detach", lambda r: r["client"]["transport_detachment"].update(detached=1)),
                ("its grant did not join", lambda r: r["server"]["grant_joins"].update(origin=1)),
                ("validated-backup state_after: malformed", lambda r: self.sample(r, "validated-backup")["state_after"].update(wire_id=True)),
                ("validated-backup state_after: malformed", lambda r: self.sample(r, "validated-backup")["state_after"].update(validated=1)),
                ("retired state_after: malformed", lambda r: self.sample(r, "retired")["state_after"].pop("local_use"))):
            with self.subTest(label=label):
                self.rejects(edit, label)

    def test_path_ids_are_the_producers_uint32(self):
        for wire_id in (-1, 2**32, True):
            with self.subTest(wire_id=wire_id):
                def out_of_range(record):
                    for phase in ("validated-backup", "retired"):
                        sample = self.sample(record, phase)
                        sample["path_id"] = wire_id
                        for field in ("state_before", "state_after"):
                            sample[field]["wire_id"] = wire_id
                self.rejects(out_of_range, "uint32")

    def test_comparison_pairs_one_qualifying_state(self):
        pairs = driver.match_lifecycle(lifecycle_record("reno"), lifecycle_record("bbrv3", heap=(5, 6, 7)))
        self.assertEqual(pairs, {"negotiated-idle": (4_000_000, 5), "validated-backup": (4_100_000, 6), "retired": (4_010_000, 7)})
        with self.assertRaisesRegex(ValueError, "one side retired to closed, the other to retained"):
            driver.match_lifecycle(lifecycle_record(retired="closed"), lifecycle_record(retired="retained"))
        relabeled = lifecycle_record()
        relabeled["client"]["samples"][1]["path_id"] = 2
        with self.assertRaises(ValueError):
            driver.match_lifecycle(lifecycle_record(), relabeled)
        for status in ("failed", "started", None):
            failed = lifecycle_record()
            failed["status"] = status
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, "pairs succeeded attempts"):
                driver.match_lifecycle(lifecycle_record(), failed)

    def test_native_lifecycle_is_refused_not_replaced(self):
        record = lifecycle_record()
        record["platform_profile"] = "darwin-arm64"
        with self.assertRaisesRegex(ValueError, "public Darwin multipath admission"):
            driver.check_lifecycle(record)
        with self.assertRaisesRegex(ValueError, "public Darwin multipath admission"):
            driver.run_lifecycle("fixture", Path("unused"), "reno", "closed", 30, {}, "darwin-arm64")


class LifecycleExecutionTests(unittest.TestCase):
    def invoke(self, root, failure=None, edit=None, extra=("--retired-lifecycle", "closed")):
        binary = root / "fixture"
        binary.write_bytes(b"fixture identity")
        output = root / "output"
        processes = {}

        class Process:
            returncode = None

            def __init__(self, role):
                self.role = role

            def wait(self, timeout=None):
                if failure == "timeout" and self.role == "client" and timeout is not None:
                    raise subprocess.TimeoutExpired("fixture", timeout)
                self.returncode = 7 if failure == "exit" and self.role == "client" else 0
                return self.returncode

            def kill(self):
                self.returncode = -9

        def launch(command, env=None, stdout=None, **kwargs):
            spec = json.loads(env["ORDINARY_COST_LIFECYCLE_SPEC"])
            self.assertIn("-test.run=^TestOrdinaryCostLifecycleRole$", command)
            self.assertNotIn("ORDINARY_COST_SPEC", env)
            if failure == "launch" and processes:
                raise OSError("second child launch failed")
            process = Process(spec["role"])
            processes[spec["role"]] = (process, spec, command)
            stdout.write("--- PASS: TestOrdinaryCostLifecycleRole (0.10s)\n")
            record = lifecycle_record(spec["controller"], spec["retired_lifecycle"])
            if edit:
                edit(record)
            Path(spec["output"]).write_text(json.dumps(record[spec["role"]]))
            return process

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(driver.platform, "platform", return_value="Linux-test"))
            stack.enter_context(mock.patch.object(driver.platform, "system", return_value="Linux"))
            stack.enter_context(mock.patch.object(driver.platform, "machine", return_value="x86_64"))
            stack.enter_context(mock.patch.object(driver.shutil, "which", return_value="taskset"))
            stack.enter_context(mock.patch.object(driver.subprocess, "run", return_value=mock.Mock(stdout=f"fixture: {driver.GO_VERSION}\n")))
            stack.enter_context(mock.patch.object(driver.subprocess, "Popen", side_effect=launch))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            code = driver.main(["--candidate", "a" * 40, "--binary", str(binary), "--output", str(output),
                                "--remaining-instances", "1", "--remaining-host-seconds", "60",
                                "--timeout-seconds", "40", "--lifecycle-memory", *extra])
        return code, json.loads((output / "summary.json").read_text()), output, processes

    def test_lifecycle_observation_is_charged_and_read_back(self):
        for controller in ("reno", "bbrv3"):
            with self.subTest(controller=controller), tempfile.TemporaryDirectory() as temporary:
                code, summary, output, processes = self.invoke(Path(temporary), extra=("--retired-lifecycle", "retained", "--controller", controller))
                self.assertEqual(code, 0, summary)
                self.assertTrue(summary["passed"])
                self.assertFalse(summary["judged"])
                self.assertEqual(summary["retired_lifecycle"], "retained")
                self.assertEqual(list(summary["go_heap_live"]), list(driver.LIFECYCLE_PHASES))
                self.assertEqual(summary["instances_charged"], 1)
                self.assertEqual(summary["attempts"][0]["status"], "succeeded")
                self.assertEqual(sorted(processes), ["client", "server"])
                for role, (process, spec, command) in processes.items():
                    self.assertEqual(spec["controller"], controller)
                    self.assertEqual(spec["retired_lifecycle"], "retained")
                    self.assertEqual(spec["address"], driver.SERVER_ADDRESS)
                    self.assertLess(spec["timeout_ns"], 40 * 10**9, "a role stops before the driver kills it")
                    self.assertEqual(command[:3], ["taskset", "-c", driver.SERVER_CPUS if role == "server" else driver.CLIENT_CPUS])
                identity_record = json.loads((output / "identity.json").read_text())
                self.assertEqual(identity_record["workload"], driver.LIFECYCLE)
                self.assertNotIn("comparator", identity_record)
                self.assertEqual(identity_record["lifecycle_boundaries"], driver.LIFECYCLE_BOUNDARIES)
                lines = (output / f"{driver.LIFECYCLE}.jsonl").read_text().splitlines()
                self.assertEqual(len(lines), 1)
                driver.check_lifecycle(json.loads(lines[0]))

    def test_failed_role_or_record_keeps_the_charge_and_reaps_both(self):
        def stale(record):
            record["client"]["samples"][2]["state_after"]["lifecycle"] = "retained"
        for failure, edit in (("launch", None), ("exit", None), ("timeout", None), ("invalid", stale)):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                code, summary, _, processes = self.invoke(Path(temporary), failure=failure, edit=edit)
                self.assertEqual(code, 1)
                self.assertFalse(summary["passed"])
                self.assertEqual(summary["instances_charged"], 1)
                self.assertEqual(summary["attempts"][0]["status"], "failed")
                self.assertTrue(all(process.returncode is not None for process, _, _ in processes.values()))
                if failure in ("exit", "timeout"):
                    self.assertEqual(processes["server"][0].returncode, -9, "the unsampled peer is killed, then reaped")

    def test_lifecycle_arguments(self):
        for extra, message in (((), "go together"),
                               (("--retired-lifecycle", "closed", "--platform-profile", "darwin-arm64"), "public Darwin multipath admission"),
                               (("--retired-lifecycle", "closed", "--cpu-profile"), "no CPU profile"),
                               (("--retired-lifecycle", "retiring"), "invalid choice")):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as temporary:
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
                    self.invoke(Path(temporary), extra=extra)
                self.assertIn(message, stderr.getvalue())
                self.assertFalse((Path(temporary) / "output").exists(), "nothing ran")
        with tempfile.TemporaryDirectory() as temporary:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
                driver.main(["--candidate", "a" * 40, "--binary", "b", "--output", str(Path(temporary) / "o"),
                             "--remaining-instances", "1", "--remaining-host-seconds", "60", "--timeout-seconds", "40",
                             "--smoke-cell", "stream-gso-on", "--retired-lifecycle", "closed"])
            self.assertIn("go together", stderr.getvalue())

    def test_short_timeout_launches_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            code, summary, _, processes = self.invoke(Path(temporary), extra=("--retired-lifecycle", "closed", "--timeout-seconds", "10"))
            self.assertEqual(code, 1)
            self.assertEqual(processes, {})
            self.assertIn(f"at least {driver.LIFECYCLE_TIMEOUT_S}", summary["error"])


def stub_binding(source, candidate, binaries, tree=None):
    """A binding record for stand-in binaries; real bindings are tested below and in
    test_candidate_binding."""
    return {"source": {"commit": candidate, "tree": "b" * 40, "head_tree": "b" * 40, "clean": True},
            "bindings": {name: {"method": "stub", "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}
                         for name, path in binaries.items()}}


class NativeBindingTests(unittest.TestCase):
    """MP-MAC #1528: on darwin-arm64 the driver refuses a test binary that is not a
    byte-identical rebuild of the clean candidate, before any output or launch."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.repo = binding_fixture.FixtureRepo(self.root)

    def run_driver(self, binary, candidate=None, profile="darwin-arm64"):
        """Run main against the fixture checkout; any role launch is recorded and fails."""
        launches, real_popen = [], subprocess.Popen

        def popen(command, *args, env=None, **kwargs):
            if env is not None and "ORDINARY_COST_SPEC" in env:
                launches.append(command)
                raise OSError("launch spy: no role runs in a binding test")
            return real_popen(command, *args, env=env, **kwargs)

        system, machine = driver.PROFILES[profile]["host"]
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(driver, "GO_VERSION", binding_fixture.GO_VERSION))
            stack.enter_context(mock.patch.object(driver.platform, "system", return_value=system))
            stack.enter_context(mock.patch.object(driver.platform, "machine", return_value=machine))
            stack.enter_context(mock.patch.object(driver.shutil, "which", return_value="taskset"))
            stack.enter_context(mock.patch.object(driver.subprocess, "Popen", side_effect=popen))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            code = driver.main(["--platform-profile", profile, "--controller", "reno", "--diagnostic-cell", "stream",
                                "--candidate", candidate or self.repo.head(), "--binary", str(binary),
                                "--source", str(self.repo.root), "--output", str(self.root / "output"),
                                "--remaining-instances", "56", "--remaining-host-seconds", "7560", "--timeout-seconds", "135"])
        return code, launches

    def refused(self, pattern, binary, candidate=None):
        with self.assertRaisesRegex(ValueError, pattern):
            self.run_driver(binary, candidate)
        self.assertFalse((self.root / "output").exists(), "refused before any output")

    def test_candidate_build_is_accepted_and_recorded(self):
        binary = self.repo.build("ordinary-cost-T27.test", tags="ordinarycost")
        code, launches = self.run_driver(binary)
        self.assertEqual(code, 1)
        self.assertEqual(len(launches), 1, "the bound binary reached its first role launch")
        identity = json.loads((self.root / "output" / "identity.json").read_text())
        self.assertEqual(identity["source"], {"commit": self.repo.head(), "tree": self.repo.tree(),
                                              "head_tree": self.repo.tree(), "clean": True})
        bound = identity["binary"]["binding"]
        self.assertEqual((bound["sha256"], bound["rebuild"]), (identity["binary"]["sha256"], "byte-identical"))
        self.assertEqual(bound["settings"]["-tags"], "ordinarycost")

    def test_stale_dirty_mismatched_or_ignored_builds_are_refused(self):
        first = self.repo.head()
        self.refused("is not the candidate's build", self.repo.stale("stale.test", tags="ordinarycost"))
        self.refused("not the candidate", self.repo.build("current.test", tags="ordinarycost"), candidate=first)
        self.repo.write("extra_ignored.go", "package bindingfixture\n\nconst Extra = 1\n")
        self.refused("recorded tree omits", self.repo.build("ignored.test", tags="ordinarycost"))
        (self.repo.root / "extra_ignored.go").unlink()
        binary = self.repo.build("dirty.test", tags="ordinarycost")
        self.repo.write("fixture.go", 'package bindingfixture\n\nconst Version = "edited"\n')
        self.refused("not clean", binary)

    def test_linux_profile_never_binds(self):
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(driver.candidate_binding, "bind", side_effect=AssertionError("bound on Linux")):
            code, summary, _ = ExecutionTests().invoke(Path(temporary), ("--smoke-cell", "stream-gso-on"))
        self.assertEqual(code, 0, summary)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_driver(self.repo.build("linux.test"), profile="linux-amd64")


VERDICT_CANDIDATE = "c" * 40


def set_cpu(record, seconds):
    record["server"]["window_cpu_s"] = seconds
    record["server"]["self_cpu"]["value"] = int(seconds * 10**9)


def empty_second(record):
    ordinary = flows(record, "ordinary")[0]
    ordinary["series"][7] = 0
    ordinary["useful_bytes"] = sum(ordinary["series"])
    resync_useful(record)


def flows(record, label):
    return [item for item in record["client"]["flows"] if item["label"] == label]


class DarwinVerdictTests(unittest.TestCase):
    """MP-MAC #1569 (protocol D12 A): the X11 verdict over the accepted attempt of rounds
    1-3, read only from each attempt's diagnostic.jsonl and identity.json."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def attempt(self, n, controller="reno", cell="stream", opted=None, record_edit=None, identity_edit=None):
        """One accepted $N/a1 directory as the driver writes it: two arm records, identity
        and a summary.json whose embedded figures contradict them."""
        directory = self.root / "cost" / controller / cell / str(n) / "a1"
        directory.mkdir(parents=True)
        records = []
        for profile in (driver.CONTROL, driver.OPTED_IN):
            record = observation(cell, profile, platform=driver.DARWIN, controller=controller)
            record.update(mode="diagnostic", candidate=VERDICT_CANDIDATE, attempt=0, round=0, seed=driver.BASE_SEED,
                          status="succeeded", occupied_s=80.0, cpu_profile=False, timing_eligible=True)
            if profile == driver.OPTED_IN and opted:
                opted(record)
            if record_edit:
                record_edit(record)
            records.append(record)
        (directory / "diagnostic.jsonl").write_text("".join(json.dumps(record) + "\n" for record in records))
        identity_record = {
            "candidate": VERDICT_CANDIDATE, "controller": controller, "platform_profile": driver.DARWIN,
            "mode": "diagnostic", "cells": [cell], "cpu_profile": False,
            "binary": {"path": "/bin/ordinary-cost-T27.test", "sha256": "9" * 64,
                       "binding": {"method": "rebuild-from-candidate/v1", "sha256": "9" * 64, "rebuild": "byte-identical"}},
            "source": {"commit": VERDICT_CANDIDATE, "tree": "8" * 40, "head_tree": "8" * 40, "clean": True},
        }
        if identity_edit:
            identity_edit(identity_record)
        (directory / "identity.json").write_text(json.dumps(identity_record))
        (directory / "summary.json").write_text(json.dumps({"passed": False, "attempts": [{"server": {"window_cpu_s": 1e9}}]}))
        return directory

    def verdict(self, attempts, extra=()):
        output = self.root / "verdict"
        argv = ["--verdict", "--platform-profile", driver.DARWIN, "--output", str(output), *extra]
        for n, directory in attempts.items():
            argv += ["--attempt", f"{n}={directory}"]
        with contextlib.redirect_stdout(io.StringIO()):
            code = driver.main(argv)
        return code, json.loads((output / "verdict.json").read_text())

    def rounds(self, **attempt):
        per_round = attempt.pop("per_round", {})
        return {n: self.attempt(n, **(attempt | per_round.get(n, {}))) for n in (1, 2, 3)}

    def refused(self, pattern, attempts, extra=()):
        with self.assertRaisesRegex(ValueError, pattern):
            self.verdict(attempts, extra)
        self.assertFalse((self.root / "verdict").exists(), "a refusal writes no verdict")

    def test_reno_cell_passes_and_names_its_inputs(self):
        attempts = self.rounds()
        before = {path: path.read_bytes() for directory in attempts.values() for path in directory.iterdir()}
        code, verdict = self.verdict(attempts)
        self.assertEqual(code, 0)
        self.assertEqual(verdict["schema"], "mp-mac-x11-verdict/1")
        self.assertEqual((verdict["judged"], verdict["passed"], verdict["failures"]), (True, True, []))
        self.assertEqual((verdict["controller"], verdict["cell"], verdict["candidate"], verdict["binary_sha256"]),
                         ("reno", "stream", VERDICT_CANDIDATE, "9" * 64))
        self.assertEqual(verdict["diagnostic"]["goodput_ratio"]["rounds"], [1.0, 1.0, 1.0])
        self.assertEqual([item["round"] for item in verdict["inputs"]], [1, 2, 3])
        for item, directory in zip(verdict["inputs"], attempts.values()):
            self.assertEqual(set(item["files"]), {"diagnostic.jsonl", "identity.json"})
            for name, entry in item["files"].items():
                self.assertEqual(entry, {"path": str(directory / name),
                                         "sha256": hashlib.sha256((directory / name).read_bytes()).hexdigest()})
        self.assertEqual(verdict["host_activity"]["2"], {driver.CONTROL: "unavailable", driver.OPTED_IN: "unavailable"})
        self.assertEqual(before, {path: path.read_bytes() for directory in attempts.values() for path in directory.iterdir()},
                         "the verdict never rewrites an input")

    def test_summary_json_is_not_an_input(self):
        attempts = self.rounds()
        _, expected = self.verdict(attempts)
        shutil.rmtree(self.root / "verdict")
        for directory in attempts.values():
            (directory / "summary.json").write_text("{not json")
        _, verdict = self.verdict(attempts)
        self.assertEqual(verdict, expected)

    def test_each_reno_rule_fails_on_its_own(self):
        def slower(record):
            scale_goodput(record, 0.9)
            set_cpu(record, 54.0)  # the same CPU per useful byte

        def control_latency(record):
            flows(record, "ordinary")[0]["control"]["p99_us"] = 2001.0

        def send_latency(record):
            record["server"]["application_send_call"]["ordinary"]["p99_us"] = 2001.0

        def timeout_close(record):
            record["client"]["flows"][0]["timeout_close"] = True

        def write_error(record):
            record["server"]["write_errors"] = 1

        def memory(record):
            end = record["server"]["peak_rss_end"]
            end["value"] = end["bytes"] = 1_126_401  # just above 1.10 × 1,024,000 bytes

        every = lambda edit: {"opted": edit}
        once = lambda edit: {"per_round": {2: {"opted": edit}}}
        for edit, failure in ((every(slower), "goodput ratio 0.900 below 0.95"),
                              (every(lambda record: set_cpu(record, 66.6)), "CPU per useful byte ratio 1.110 above 1.1"),
                              (every(control_latency), "control p99 1 us over its limit"),
                              (every(send_latency), "application send-call p99 1 us over its limit"),
                              (once(timeout_close), "timeout-only close in rounds [2]"),
                              (once(write_error), "write error or non-timeout close in rounds [2]"),
                              (once(empty_second), "fair progress: an empty second in rounds [2]"),
                              (once(memory), "memory kept growing in rounds [2]")):
            with self.subTest(failure=failure):
                shutil.rmtree(self.root, ignore_errors=True)
                self.root.mkdir()
                code, verdict = self.verdict(self.rounds(**edit))
                self.assertEqual(code, 1)
                self.assertEqual((verdict["judged"], verdict["passed"], verdict["failures"]), (True, False, [failure]))

    def test_darwin_memory_rule_reads_normalized_peak_rss_bytes(self):
        def at_ceiling(record):
            end = record["server"]["peak_rss_end"]
            end["value"] = end["bytes"] = 1_126_400  # exactly 1.10 × the sample: bounded

        code, verdict = self.verdict(self.rounds(opted=at_ceiling))
        self.assertEqual((code, verdict["failures"]), (0, []))
        self.assertEqual(verdict["diagnostic"]["peak_rss_bytes"][driver.OPTED_IN], [1_126_400] * 3)
        self.assertNotIn("peak_rss_kb", verdict["diagnostic"])

    def test_bbr_is_reported_unjudged_on_every_cell(self):
        for cell in driver.NATIVE_CELLS:
            if cell == "mixed-bulk":
                continue  # its opted-in arm needs the D14 lifts
            with self.subTest(cell=cell):
                shutil.rmtree(self.root, ignore_errors=True)
                self.root.mkdir()
                code, verdict = self.verdict(self.rounds(controller="bbrv3", cell=cell, opted=lambda r: set_cpu(r, 90.0)))
                self.assertEqual(code, 0)
                self.assertEqual((verdict["judged"], verdict["passed"]), (False, None))
                self.assertNotIn("diagnostic", verdict)
                self.assertEqual(verdict["observations"]["cpu_per_useful_byte_ratio"]["median"], 1.5)

    def test_identity_that_differs_across_rounds_is_refused(self):
        def identity(**changes):
            return {"per_round": {3: {"identity_edit": lambda record: record.update(changes)}}}

        def records(**changes):
            return {"per_round": {3: {"record_edit": lambda record: record.update(changes)}}}

        # Round 3 is self-consistent and bound; it differs from rounds 1 and 2 only.
        other_candidate = {"per_round": {3: {
            "identity_edit": lambda record: record.update(candidate="d" * 40, source=dict(record["source"], commit="d" * 40)),
            "record_edit": lambda record: record.update(candidate="d" * 40)}}}
        for attempt, pattern in (
                (other_candidate, "do not share one candidate"),
                (identity(binary={"sha256": "7" * 64, "binding": {"sha256": "7" * 64}}), "do not share one binary"),
                (identity(controller="bbrv3"), "controller"),
                (identity(cells=["datagram"]), "cell"),
                (identity(mode="smoke"), "diagnostic"),
                (identity(cpu_profile=True), "CPU profil"),
                (identity(platform_profile=driver.LINUX), "darwin-arm64"),
                (records(candidate="d" * 40), "candidate"),
                ({"per_round": {3: {"controller": "bbrv3"}}}, "controller"),
                ({"per_round": {3: {"cell": "datagram"}}}, "cell"),
                (identity(binary={"sha256": "9" * 64}), "binding"),
                (identity(source={"commit": "d" * 40}), "binding")):
            with self.subTest(pattern=pattern, attempt=attempt):
                shutil.rmtree(self.root, ignore_errors=True)
                self.root.mkdir()
                self.refused(pattern, self.rounds(**attempt))

    def test_a_missing_digest_is_not_a_binding(self):
        def unbound(record):
            record["binary"] = {"path": "/bin/ordinary-cost-T27.test", "sha256": None, "binding": {}}

        self.refused("binding", self.rounds(identity_edit=unbound))
        shutil.rmtree(self.root)
        self.root.mkdir()
        self.refused("binding", self.rounds(identity_edit=lambda record: record["binary"].update(sha256="9" * 63)))

    def test_one_attempt_cannot_stand_for_two_rounds(self):
        attempts = self.rounds()
        self.refused("round 2.* is round 1's attempt", attempts | {2: attempts[1]})
        self.refused("round 3.* is round 1's attempt", attempts | {3: attempts[1].parent / "." / "a1"})

    def test_malformed_input_shapes_name_their_file(self):
        for n, name, malform in ((2, "identity.json", lambda text: "[]"), (3, "diagnostic.jsonl", lambda text: "[]\n[]\n"),
                                 (1, "identity.json", lambda text: json.dumps(json.loads(text) | {"binary": []}))):
            with self.subTest(n=n, name=name):
                shutil.rmtree(self.root, ignore_errors=True)
                self.root.mkdir()
                attempts = self.rounds()
                path = attempts[n] / name
                path.write_text(malform(path.read_text()))
                self.refused(f"round {n} attempt .*{name}", attempts)

    def test_malformed_input_sets_are_refused(self):
        attempts = self.rounds()
        self.refused("rounds 1, 2 and 3", {1: attempts[1], 2: attempts[2]})
        self.refused("rounds 1, 2 and 3", attempts | {4: attempts[3]})
        self.refused("darwin-arm64", attempts, ("--platform-profile", driver.LINUX))
        lines = (attempts[2] / "diagnostic.jsonl").read_text().splitlines()
        (attempts[2] / "diagnostic.jsonl").write_text(lines[0] + "\n")
        self.refused("exactly one unregistered and one opted-in", attempts)
        (attempts[2] / "diagnostic.jsonl").write_text("\n".join(lines + lines[:1]) + "\n")
        self.refused("exactly one unregistered and one opted-in", attempts)
        record = json.loads(lines[1])
        record["server"]["granted"] = False  # fails the existing readback
        (attempts[2] / "diagnostic.jsonl").write_text(lines[0] + "\n" + json.dumps(record) + "\n")
        self.refused("grant does not match", attempts)
        (attempts[2] / "diagnostic.jsonl").unlink()
        self.refused("diagnostic.jsonl", attempts)


if __name__ == "__main__":
    unittest.main()
