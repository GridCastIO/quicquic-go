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
from pathlib import Path
from unittest import mock

import ordinary_cost as driver


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


def unavailable(unit, reason="no producer"):
    return {"value": None, "unit": unit, "source": "fixture producer", "available": False, "reason": reason}


def identity(platform):
    goos, goarch = driver.PROFILES[platform]["identity"]
    return {"profile": platform, "goos": goos, "goarch": goarch}


def lost(controller):
    return metric(0, "packets") if controller == "reno" else unavailable("packets", "only Reno/CUBIC counts lost packets")


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
            "self_cpu": metric(60 * 10**9, "ns"),
            "peak_rss_at_sample": metric(rss, rss_unit, bytes=rss * scale),
            "peak_rss_end": metric(rss, rss_unit, bytes=rss * scale),
            "write_errors": 0,
            "joined": profile == "opted-in",
            "application_send_call_boundary": driver.METRIC_BOUNDARIES["application_send_call"],
            "application_send_call": {"ordinary": {"count": 6000, "p99_us": 1000.0}},
            "connections": [connection],
        },
        "client": {"go": driver.GO_VERSION, "controller": controller, "platform": identity(platform),
                   "window_cpu_s": 30.0, "self_cpu": metric(30 * 10**9, "ns"), "flows": [flow()]},
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
    record["client"]["useful_bytes"] = metric(sum(f["useful_bytes"] for f in record["client"]["flows"]), "bytes")
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
                        super().__init__([sys.executable, "-c", "import signal; signal.pause()"], **kwargs)
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
        for failure in ("goodput", "write", "close", "timeout"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                def fail(record):
                    if record["cell"] != "mixed-bulk" or record["profile"] != driver.OPTED_IN:
                        return
                    if failure == "goodput":
                        scale_goodput(record, 0.5)
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
                self.assertEqual(summary["diagnostic"]["packets_lost"], {"unregistered": [None], "opted-in": [None]})

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
                self.assertFalse(summary["diagnostic"]["passed"], "the ratios are still reported")
                if not judged:
                    self.assertIn("observations", summary["judgment"])

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
        record["server"]["connections"][0]["packets_lost_metric"] = metric(0, "packets")
        with self.assertRaisesRegex(ValueError, "lost"):
            driver.check_observation(record)
        record = observation(controller="bbrv3")
        record["server"]["connections"][0]["packets_lost"] = 0
        with self.assertRaisesRegex(ValueError, "lost"):
            driver.check_observation(record)
        record = observation()
        record["server"]["connections"][0]["packets_lost_metric"] = unavailable("packets")
        with self.assertRaisesRegex(ValueError, "lost"):
            driver.check_observation(record)

    def test_malformed_metric_fails(self):
        cases = {
            "missing": lambda r: r["server"].pop("self_cpu"),
            "value without availability": lambda r: r["server"]["self_cpu"].update(available=False),
            "unavailable without reason": lambda r: r["server"].update(self_cpu=unavailable("ns", "")),
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

    def test_privilege_failure_is_unavailable_never_quiet(self):
        with tempfile.TemporaryDirectory() as temporary:
            activity = self.run_sampler(Path(temporary),
                "import sys; sys.stderr.write('powermetrics must be invoked as the superuser\\n'); sys.exit(1)")
        self.assertEqual(activity["status"], "unavailable")
        self.assertIn("superuser", activity["reason"])
        self.assertEqual(activity["exit"], 1)

    def test_sampler_output_is_preserved_and_parsed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = textwrap.dedent(f"""
                import signal, sys, time
                sys.stdout.buffer.write(open({str(FIXTURE)!r}, 'rb').read()); sys.stdout.flush()
                signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
                time.sleep(60)
            """)
            activity = self.run_sampler(root, script)
            self.assertEqual(activity["status"], "observed", activity)
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

    def test_interrupted_stop_kills_and_joins_before_unwinding(self):
        with tempfile.TemporaryDirectory() as temporary:
            sampler = driver.HostSampler([sys.executable, "-c",
                "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"], Path(temporary))
            sampler.start()
            time.sleep(0.5)  # let the child ignore SIGTERM before it is stopped
            process, real_wait = sampler.process, sampler.process.wait

            def interrupted(timeout=None):
                if timeout is not None:
                    raise KeyboardInterrupt("SIGTERM")
                return real_wait()

            with mock.patch.object(process, "wait", side_effect=interrupted), self.assertRaises(KeyboardInterrupt):
                sampler.finish(0, 0)
            self.assertEqual(process.returncode, -signal.SIGKILL)
            with self.assertRaises(ProcessLookupError):
                os.kill(process.pid, 0)

    def test_unresponsive_sampler_is_killed_and_joined(self):
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(driver, "SAMPLER_STOP_S", 0.3):
                activity = self.run_sampler(Path(temporary),
                    "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)")
        self.assertTrue(activity["joined"])
        self.assertEqual(activity["exit"], -signal.SIGKILL)
        self.assertEqual(activity["status"], "inconclusive")


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
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(driver.HostSampler, "finish", side_effect=KeyboardInterrupt("SIGTERM")):
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

    def test_sigterm_reaps_roles_and_sampler(self):
        self.exercise_sigterm_during_roles(native=True)


if __name__ == "__main__":
    unittest.main()
