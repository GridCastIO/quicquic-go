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


SPEC = importlib.util.spec_from_file_location("native_darwin", Path(__file__).with_name("native_darwin.py"))
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)

PRESSURE = runner.PROFILES["pressure"]
IDENTITY = {"go": "go1.27.4", "goos": "darwin", "goarch": "arm64"}


# What the producer records for each family, as printed by Go's UDP addresses.
TUPLES = {
    "ipv4": ("0.0.0.0:5000", "127.0.0.1:6000", "127.0.0.1:6000", "127.0.0.1:5000"),
    "ipv6": ("[::]:5000", "[::1]:6000", "[::1]:6000", "[::1]:5000"),
    "dual-stack-mapped-ipv4": ("[::]:5000", "127.0.0.1:6000", "[::ffff:127.0.0.1]:6000", "127.0.0.1:5000"),
    "dual-stack-native-ipv6": ("[::]:5000", "[::1]:6000", "[::1]:6000", "[::1]:5000"),
}


def family_facts(name):
    granted, peer, inbound, outbound = TUPLES[name]
    return {
        "family": name, "granted_local": granted, "peer": peer, "inbound_source": inbound,
        "inbound_destination": runner.FAMILIES[name], "inbound_interface": 1, "inbound_ecn": "CE", "outbound_accepted": 1,
        "outbound_source": outbound, "outbound_ecn": "ECT(0)", "joined": True,
    }


# D7's approved pressure load, which socket-pressure readback pins.
PARTICIPANTS, REQUESTS, MEMBERS = 16, 64, 32
WRITES = PARTICIPANTS * len(runner.LANES) * REQUESTS * MEMBERS


def contention_facts(participants=PARTICIPANTS, requests=REQUESTS, members=MEMBERS):
    """A complete observation, as the Go fixture records one, with no pressure wait."""
    lanes = []
    for participant in range(participants):
        for lane in runner.LANES:
            lanes.append({
                "participant": participant, "lane": lane, "offers": requests + 2, "admitted": requests, "refused": 2, "closed": 0,
                "results": requests, "withdrawn": 0, "accepted": requests * members, "uncertain": 0, "unsubmitted": 0, "failed": 0,
                "diagnostics": requests, "occupancy_max": 2, "native_return_to_take_max_ns": 25000,
            })
    return {
        "status": "complete", "pressure_wait": "not-observed", "fault": "none", "unfinished_participants": 0, "diagnostics_dropped": 0,
        "load": {"participants": participants, "requests": requests, "members": members, "payload": 1200, "budget_ms": 1000, "window_ms": 20000},
        "writer": {
            "writes": participants * 3 * requests * members, "max_write_ns": 60000, "long_writes": 0, "deadline_waits": 0,
            "errors": {name: 0 for name in runner.ERROR_CLASSES},
        },
        "lanes": lanes, "participant_occupancy_max": [4] * participants,
    }


def record_for(name, **changes):
    if name in runner.FAMILIES:
        facts = family_facts(name)
    elif name in runner.CONTENTION_CASES:
        facts = contention_facts()
    else:
        facts = dict(runner.FIXED_FACTS[name])
    record = {"schema": runner.SCHEMA, "case": name, "go": "go1.27.4", "goos": "darwin", "goarch": "arm64", "facts": facts}
    record.update(changes)
    return record


def passing_output(name):
    return f"=== RUN   {runner.TEST}/{name}\n--- PASS: {runner.TEST} (0.00s)\n    --- PASS: {runner.TEST}/{name} (0.00s)\nPASS\n"


class OutputTests(unittest.TestCase):
    def test_exactly_one_pass_is_required(self):
        runner.check_output("ipv4", passing_output("ipv4"))
        for output in ("PASS\n", passing_output("ipv6"), passing_output("ipv4") + passing_output("ipv4")):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, "exactly once"):
                runner.check_output("ipv4", output)

    def test_skip_or_failure_fails(self):
        for word in ("SKIP", "FAIL"):
            with self.subTest(word=word), self.assertRaisesRegex(ValueError, word):
                runner.check_output("ipv4", passing_output("ipv4") + f"    --- {word}: {runner.TEST}/ipv4 (0.00s)\n")


class RecordTests(unittest.TestCase):
    def test_every_declared_case_accepts_its_record(self):
        for name in runner.CASES:
            with self.subTest(name=name):
                runner.check_record(name, IDENTITY, record_for(name))

    def test_identity_mismatch_fails(self):
        for field, value in (("schema", "native-darwin-case/v0"), ("case", "ipv6"), ("go", "go1.26.11"), ("goos", "linux"), ("goarch", "amd64")):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                runner.check_record("ipv4", IDENTITY, record_for("ipv4", **{field: value}))

    def test_unknown_or_missing_fields_fail(self):
        with self.assertRaisesRegex(ValueError, "fields"):
            runner.check_record("ipv4", IDENTITY, record_for("ipv4", extra=True))
        incomplete = record_for("ipv4")
        del incomplete["facts"]
        with self.assertRaisesRegex(ValueError, "fields"):
            runner.check_record("ipv4", IDENTITY, incomplete)
        for facts in ({**family_facts("ipv4"), "unexpected": 1}, {k: v for k, v in family_facts("ipv4").items() if k != "inbound_ecn"}):
            with self.subTest(facts=sorted(facts)), self.assertRaisesRegex(ValueError, "facts"):
                runner.check_record("ipv4", IDENTITY, record_for("ipv4", facts=facts))

    def test_semantic_facts_are_checked(self):
        for key, value in (("family", "ipv6"), ("outbound_accepted", 0), ("joined", False), ("inbound_interface", 0)):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, key):
                runner.check_record("ipv4", IDENTITY, record_for("ipv4", facts={**family_facts("ipv4"), key: value}))
        changed = {**runner.FIXED_FACTS["grant-refusal"], "held_socket": "accepted"}
        with self.assertRaisesRegex(ValueError, "held_socket"):
            runner.check_record("grant-refusal", IDENTITY, record_for("grant-refusal", facts=changed))

    def test_recorded_tuples_match_the_family(self):
        contradictions = {
            "ipv6": {"peer": "127.0.0.1:6000", "inbound_source": "127.0.0.1:6000", "outbound_source": "127.0.0.1:5000"},
            "ipv4": {"peer": None},
            "dual-stack-mapped-ipv4": {"outbound_source": "127.0.0.1:5001"},
            "dual-stack-native-ipv6": {"inbound_source": "[::1]:6001"},
        }
        for name, changes in contradictions.items():
            for key, value in changes.items():
                with self.subTest(name=name, key=key), self.assertRaisesRegex(ValueError, key):
                    runner.check_record(name, IDENTITY, record_for(name, facts={**family_facts(name), key: value}))
        with self.assertRaisesRegex(ValueError, "inbound_source"):
            runner.check_record("dual-stack-mapped-ipv4", IDENTITY, record_for("dual-stack-mapped-ipv4", facts={**family_facts("dual-stack-mapped-ipv4"), "inbound_source": "127.0.0.1:6000"}))

    def test_malformed_record_fails(self):
        for text in ("", "{", "[]", '"record"'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                runner.parse_record(text)


class ContentionTests(unittest.TestCase):
    def check(self, facts, name="scalar-contention"):
        profile = PRESSURE if name == "socket-pressure" else runner.SCALAR
        runner.check_record(name, IDENTITY, record_for(name, facts=facts), profile)

    def test_complete_observation_is_accepted(self):
        for name in runner.CONTENTION_CASES:
            with self.subTest(name=name):
                self.check(contention_facts(), name)

    def test_lane_accounting_must_add_up(self):
        for key, value in (("offers", 4), ("refused", 3), ("withdrawn", 1), ("accepted", 5), ("failed", REQUESTS + 1), ("admitted", 4), ("occupancy_max", REQUESTS + 1), ("occupancy_max", 0)):
            facts = contention_facts()
            facts["lanes"][1][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "lane 1"):
                self.check(facts, "socket-pressure")

    def test_shape_is_declared(self):
        changes = (
            ("lanes", lambda facts: facts["lanes"].pop()),
            ("lane 2 is", lambda facts: facts["lanes"][2].update(lane="path0")),
            ("lane 0 fields", lambda facts: facts["lanes"][0].pop("diagnostics")),
            ("lane 0 has invalid", lambda facts: facts["lanes"][0].update(refused=True)),
            ("writer errors fields", lambda facts: facts["writer"]["errors"].pop("enobufs")),
            ("participant_occupancy_max", lambda facts: facts["participant_occupancy_max"].pop()),
            ("fault", lambda facts: facts.update(fault="unknown")),
            ("facts", lambda facts: facts.pop("writer")),
        )
        for pattern, change in changes:
            facts = contention_facts()
            change(facts)
            with self.subTest(pattern=pattern), self.assertRaisesRegex(ValueError, pattern):
                self.check(facts, "socket-pressure")

    def test_writer_observations_must_agree(self):
        for key, value in (("writes", 1), ("deadline_waits", 1), ("long_writes", WRITES + 1)):
            facts = contention_facts()
            facts["writer"][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "writ"):
                self.check(facts, "socket-pressure")

    def test_status_and_pressure_follow_the_counts(self):
        # An observed wait stands in any status.
        observed = contention_facts()
        observed["writer"]["errors"]["deadline"] = observed["writer"]["deadline_waits"] = 1
        observed["lanes"][0].update(accepted=REQUESTS * MEMBERS - 1, uncertain=1, failed=1)
        observed["pressure_wait"] = "observed"
        self.check(observed, "socket-pressure")
        # A wait whose timeout shows in no failed result contradicts the outcomes.
        hidden = {**observed, "lanes": [dict(lane) for lane in observed["lanes"]]}
        hidden["lanes"][0].update(accepted=REQUESTS * MEMBERS, uncertain=0, failed=0)
        with self.assertRaisesRegex(ValueError, "pressure wait"):
            self.check(hidden, "socket-pressure")
        # A load that didn't finish in its window, or whose endpoint faulted, is
        # interrupted even when every count is full.
        for change in ({"unfinished_participants": 1}, {"fault": "overdue"}):
            late = {**contention_facts(), **change}
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "imply"):
                self.check(late, "socket-pressure")
            self.check({**late, "status": "interrupted", "pressure_wait": "unknown"}, "socket-pressure")
        with self.assertRaisesRegex(ValueError, "unfinished"):
            self.check({**contention_facts(), "unfinished_participants": PARTICIPANTS + 1, "status": "interrupted", "pressure_wait": "unknown"}, "socket-pressure")
        # A dropped diagnostic or a lagging sink is missing coverage: no negative claim.
        dropped = contention_facts()
        dropped.update(diagnostics_dropped=3, status="incomplete-coverage", pressure_wait="unknown")
        self.check(dropped, "socket-pressure")
        lagging = contention_facts()
        lagging["lanes"][4]["diagnostics"] = 2
        lagging.update(status="incomplete-coverage", pressure_wait="unknown")
        self.check(lagging, "socket-pressure")
        # An interrupted load withdrew or never offered some requests.
        interrupted = contention_facts()
        interrupted["lanes"][3].update(results=REQUESTS - 1, withdrawn=1, accepted=(REQUESTS - 1) * MEMBERS, diagnostics=REQUESTS - 1)
        interrupted.update(status="interrupted", pressure_wait="unknown", unfinished_participants=1)
        self.check(interrupted, "socket-pressure")
        for facts, status, pressure in ((dropped, "incomplete-coverage", "not-observed"), (interrupted, "complete", "unknown"), (observed, "complete", "not-observed")):
            changed = {**facts, "status": status, "pressure_wait": pressure}
            with self.subTest(status=status, pressure=pressure), self.assertRaisesRegex(ValueError, "imply"):
                self.check(changed, "socket-pressure")

    def test_development_case_needs_complete_progress(self):
        interrupted = contention_facts()
        interrupted["lanes"][3].update(results=REQUESTS - 1, withdrawn=1, accepted=(REQUESTS - 1) * MEMBERS, diagnostics=REQUESTS - 1)
        interrupted.update(status="interrupted", pressure_wait="unknown")
        faulted = {**contention_facts(), "fault": "overdue", "status": "interrupted", "pressure_wait": "unknown"}
        stalled = contention_facts()
        stalled["lanes"][2].update(accepted=0, unsubmitted=REQUESTS * MEMBERS, failed=REQUESTS)
        for name, facts in (("interrupted", interrupted), ("faulted", faulted), ("stalled", stalled)):
            self.check(facts, "socket-pressure")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "development case"):
                self.check(facts)


class PressureLoadTests(unittest.TestCase):
    """MP-MAC #1564: socket-pressure readback pins D7's load and every contention
    record bounds the writer's native calls by its admitted members."""

    def deviations(self):
        for field in runner.LOAD_FIELDS:
            facts = contention_facts()
            facts["load"][field] += 1
            yield field, facts

    def test_only_the_d7_load_is_a_pressure_record(self):
        runner.check_record("socket-pressure", IDENTITY, record_for("socket-pressure"), PRESSURE)
        for field, facts in self.deviations():
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "not the D7 load"):
                runner.check_record("socket-pressure", IDENTITY, record_for("socket-pressure", facts=facts), PRESSURE)
        # The scalar development case keeps its own load, which the pin never reads.
        scalar = contention_facts(participants=3, requests=8, members=2)
        scalar["load"]["window_ms"] = 10000
        runner.check_record("scalar-contention", IDENTITY, record_for("scalar-contention", facts=scalar))
        with self.assertRaisesRegex(ValueError, "not the D7 load"):
            runner.check_record("socket-pressure", IDENTITY, record_for("socket-pressure", facts=scalar), PRESSURE)

    def test_readback_pins_the_d7_load(self):
        approved = ResultsTests.results(self, PRESSURE)
        runner.validate_results(approved, "pressure")
        for field, facts in self.deviations():
            results = ResultsTests.results(self, PRESSURE)
            results["instances"][0]["record"] = record_for("socket-pressure", facts=facts)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "not the D7 load"):
                runner.validate_results(results, "pressure")

    def test_a_run_refuses_another_load(self):
        output = f"=== RUN   {PRESSURE.test}/socket-pressure\n--- PASS: {PRESSURE.test} (20.00s)\n    --- PASS: {PRESSURE.test}/socket-pressure (20.00s)\nPASS\n"
        records = [("approved", record_for("socket-pressure"))]
        records += [(field, record_for("socket-pressure", facts=facts)) for field, facts in self.deviations()]
        for field, record in records:
            with self.subTest(field=field):
                directory = tempfile.TemporaryDirectory()
                self.addCleanup(directory.cleanup)
                body = f"json.dump({record!r}, open(os.environ['{runner.RECORD_ENV}'], 'w'))\nprint({output!r})"
                binary = fake_binary(directory.name, body)
                instance, failure = runner.run_case(binary, "socket-pressure", Path(directory.name) / "out", IDENTITY, 10, PRESSURE)
                if field == "approved":
                    self.assertIsNone(failure)
                    self.assertEqual(record, instance["record"])
                else:
                    self.assertRegex(failure, "not the D7 load")

    def test_writes_are_bounded_by_admitted_members(self):
        for name in runner.CONTENTION_CASES:
            profile = PRESSURE if name == "socket-pressure" else runner.SCALAR
            at = contention_facts()
            self.assertEqual(WRITES, at["writer"]["writes"])
            runner.check_record(name, IDENTITY, record_for(name, facts=at), profile)
            above = contention_facts()
            above["writer"]["writes"] = WRITES + 1
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, f"{WRITES + 1} native writes exceed the {WRITES} admitted members"):
                runner.check_record(name, IDENTITY, record_for(name, facts=above), profile)
        # An interrupted load that admitted one request fewer has a smaller bound.
        short = contention_facts()
        short["lanes"][3].update(offers=REQUESTS + 1, admitted=REQUESTS - 1, results=REQUESTS - 1, accepted=(REQUESTS - 1) * MEMBERS, diagnostics=REQUESTS - 1)
        short.update(status="interrupted", pressure_wait="unknown")
        short["writer"]["writes"] = WRITES - MEMBERS
        runner.check_record("socket-pressure", IDENTITY, record_for("socket-pressure", facts=short), PRESSURE)
        short["writer"]["writes"] = WRITES - MEMBERS + 1
        with self.assertRaisesRegex(ValueError, "exceed"):
            runner.check_record("socket-pressure", IDENTITY, record_for("socket-pressure", facts=short), PRESSURE)

    def test_the_pin_is_the_go_fixtures_load(self):
        root = Path(__file__).resolve().parents[2]
        source = (root / "native_darwin_pressure_test.go").read_text()
        match = re.search(
            r"var nativeDarwinPressureLoad = nativeDarwinLoad\{\s*participants: (\d+), requests: (\d+), members: endpointBatch, payload: (\d+), budget: time\.Second, window: (\d+) \* time\.Second,\s*\}",
            source,
        )
        self.assertIsNotNone(match, "nativeDarwinPressureLoad changed shape; re-derive the D7 pin")
        batch = re.search(r"^\s*endpointBatch\s*=\s*(\d+)$", (root / "native_endpoint.go").read_text(), re.MULTILINE)
        self.assertIsNotNone(batch)
        participants, requests, payload, window = map(int, match.groups())
        go = {"participants": participants, "requests": requests, "members": int(batch.group(1)), "payload": payload, "budget_ms": 1000, "window_ms": window * 1000}
        self.assertEqual(go, runner.PRESSURE_LOAD)
        self.assertEqual(WRITES, runner.PRESSURE_LOAD["participants"] * len(runner.LANES) * runner.PRESSURE_LOAD["requests"] * runner.PRESSURE_LOAD["members"])
        self.assertEqual(98304, WRITES, "D7: at most 98,304 writes")


class AccountingTests(unittest.TestCase):
    def test_each_case_exactly_once(self):
        runner.check_accounting(list(runner.CASES))
        with self.assertRaisesRegex(ValueError, "missing.*ipv6"):
            runner.check_accounting([name for name in runner.CASES if name != "ipv6"])
        with self.assertRaisesRegex(ValueError, "duplicate.*ipv4"):
            runner.check_accounting([*runner.CASES, "ipv4"])
        with self.assertRaisesRegex(ValueError, "unknown.*ipv7"):
            runner.check_accounting([*runner.CASES, "ipv7"])

    def test_each_profile_owns_its_cases(self):
        runner.check_accounting(list(PRESSURE.cases), PRESSURE)
        with self.assertRaisesRegex(ValueError, "unknown.*ipv4"):
            runner.check_accounting([*PRESSURE.cases, "ipv4"], PRESSURE)
        with self.assertRaisesRegex(ValueError, "unknown.*socket-pressure"):
            runner.check_accounting([*runner.CASES, "socket-pressure"])
        with self.assertRaisesRegex(ValueError, "not a scalar case"):
            runner.check_record("socket-pressure", IDENTITY, record_for("socket-pressure"))
        with self.assertRaisesRegex(ValueError, "not a pressure case"):
            runner.check_record("scalar-contention", IDENTITY, record_for("scalar-contention"), PRESSURE)
        self.assertIn("scalar-contention", runner.SCALAR.cases)
        self.assertEqual("-buildvcs=false -tags=nativepressure", PRESSURE.build["GOFLAGS"])
        for profile in (runner.SCALAR, runner.PROFILES["blocked-writer"]):
            self.assertNotIn("nativepressure", profile.build["GOFLAGS"], "no other profile builds the pressure observation")
        self.assertEqual("-test.run=^TestNativeDarwinPressure$/^socket-pressure$", runner.command_for("b", "socket-pressure", PRESSURE)[1])


class IdentityTests(unittest.TestCase):
    def test_only_native_darwin_arm64(self):
        runner.check_native({"system": "Darwin", "machine": "arm64", "proc_translated": "0"})
        for identity in (
            {"system": "Linux", "machine": "arm64", "proc_translated": "0"},
            {"system": "Darwin", "machine": "x86_64", "proc_translated": "0"},
            {"system": "Darwin", "machine": "arm64", "proc_translated": "1"},
        ):
            with self.subTest(identity=identity), self.assertRaisesRegex(ValueError, "native Darwin arm64"):
                runner.check_native(identity)


def fake_binary(directory, body):
    """An executable standing in for the test binary; it gets the case selector."""
    path = Path(directory) / "fake.test"
    path.write_text(f"#!{sys.executable}\nimport json, os, subprocess, sys, time\nname = sys.argv[1].rsplit('^', 1)[1].rstrip('$')\n{body}\n")
    path.chmod(0o755)
    return path


class RunCaseTests(unittest.TestCase):
    def run_fake(self, body, timeout=10):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        binary = fake_binary(directory.name, body)
        record, failure = runner.run_case(binary, "ipv4", Path(directory.name) / "out", IDENTITY, timeout)
        return Path(directory.name), record, failure

    def test_passing_case_with_record(self):
        body = (
            f"json.dump({record_for('ipv4')!r}, open(os.environ['{runner.RECORD_ENV}'], 'w'))\n"
            f"print({passing_output('ipv4')!r})"
        )
        directory, record, failure = self.run_fake(body)
        self.assertIsNone(failure)
        self.assertEqual(0, record["exit"])
        self.assertEqual(record_for("ipv4"), record["record"])
        self.assertTrue((directory / "out" / "ipv4" / "test.log").exists())

    def test_missing_record_fails(self):
        _, _, failure = self.run_fake(f"print({passing_output('ipv4')!r})")
        self.assertRegex(failure, "no case record")

    def test_skipped_case_fails(self):
        body = (
            f"json.dump({record_for('ipv4')!r}, open(os.environ['{runner.RECORD_ENV}'], 'w'))\n"
            f"print('--- SKIP: {runner.TEST}/ipv4 (0.00s)')"
        )
        _, _, failure = self.run_fake(body)
        self.assertRegex(failure, "SKIP")

    def test_nonzero_exit_fails(self):
        _, record, failure = self.run_fake("sys.exit(3)")
        self.assertEqual("exit 3", failure)
        self.assertEqual(3, record["exit"])

    def test_timeout_after_the_leader_exits_kills_the_pipe_holder(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        marker = Path(directory.name) / "holder.pid"
        # The leader exits at once; its child inherits stdout and keeps the pipe open.
        body = (
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            f"open({str(marker)!r}, 'w').write(str(child.pid))"
        )
        binary = fake_binary(directory.name, body)
        started = time.monotonic()
        _, failure = runner.run_case(binary, "ipv4", Path(directory.name) / "out", IDENTITY, 1)
        self.assertLess(time.monotonic() - started, 30)
        self.assertRegex(failure, "timeout")
        holder = int(marker.read_text())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(holder, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            self.fail("the pipe holder survived the timeout")

    def test_timeout_kills_and_reaps_the_process_group(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        marker = Path(directory.name) / "grandchild.pid"
        body = (
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            f"open({str(marker)!r}, 'w').write(str(child.pid))\n"
            "time.sleep(60)"
        )
        binary = fake_binary(directory.name, body)
        started = time.monotonic()
        record, failure = runner.run_case(binary, "ipv4", Path(directory.name) / "out", IDENTITY, 1)
        self.assertLess(time.monotonic() - started, 30)
        self.assertRegex(failure, "timeout")
        self.assertIsNone(record["exit"])
        grandchild = int(marker.read_text())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(grandchild, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            self.fail("the case's grandchild survived the timeout")


class SourceTests(unittest.TestCase):
    def test_tree_is_the_built_working_tree(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        source = Path(directory.name)
        git = ("git", "-c", "user.name=t", "-c", "user.email=t@example.invalid")
        runner.capture(*git, "init", "-q", cwd=source)
        (source / "a.go").write_text("package a\n")
        runner.capture(*git, "add", "a.go", cwd=source)
        runner.capture(*git, "commit", "-q", "-m", "a", cwd=source)
        clean = runner.source_identity(source)
        self.assertTrue(clean["clean"])
        self.assertEqual(clean["head_tree"], clean["tree"])
        (source / "b.go").write_text("package a\n")
        dirty = runner.source_identity(source)
        self.assertFalse(dirty["clean"])
        self.assertEqual(clean["head_tree"], dirty["head_tree"])
        self.assertNotEqual(dirty["head_tree"], dirty["tree"], "the untracked file is part of the built tree")
        self.assertEqual("?? b.go", runner.capture("git", "status", "--porcelain", cwd=source), "the real index is untouched")


class BuildSourceTests(unittest.TestCase):
    def test_go_list_stream_yields_the_test_builds_module_inputs(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / "go.mod").write_text("module example\n")
        (root / "go.sum").write_text("")
        (root / "dep").mkdir()
        module = {"Path": "example", "Main": True, "GoMod": str(root / "go.mod")}
        packages = [
            {"Dir": "/goroot/src/fmt", "Standard": True, "GoFiles": ["print.go"]},
            {"Dir": "/cache/other", "Module": {"Path": "other", "Main": False}, "GoFiles": ["other.go"]},
            {"Dir": str(root / "dep"), "Module": module, "GoFiles": ["dep.go"], "TestGoFiles": ["dep_test.go"], "XTestGoFiles": ["x_test.go"]},
            {"Dir": str(root), "Module": module, "GoFiles": ["a.go"], "TestGoFiles": ["a_test.go"], "EmbedFiles": ["data.txt"], "IgnoredGoFiles": ["other.go"]},
            {"Dir": str(root), "Module": module, "XTestGoFiles": ["b_test.go"], "SFiles": ["asm.s"]},
            {"Dir": "/cache/b0", "Module": module, "GoFiles": ["testmain.go"]},
        ]
        stream = "\n".join(json.dumps(package, indent=2) for package in packages) + "\n"
        expected = {root / name for name in ("dep/dep.go", "a.go", "a_test.go", "data.txt", "b_test.go", "asm.s", "go.mod", "go.sum")}
        self.assertEqual({path.resolve() for path in expected}, runner.parse_go_list(stream, root))
        with self.assertRaises(ValueError):
            runner.parse_go_list(stream + "{", root)

    def test_build_reading_unrecorded_source_is_refused(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        source = Path(directory.name)
        git = ("git", "-c", "user.name=t", "-c", "user.email=t@example.invalid")
        runner.capture(*git, "init", "-q", cwd=source)
        (source / ".gitignore").write_text("mockgen_tmp.go\nstaged_tmp.go\n")
        (source / "a.go").write_text("package a\n")
        runner.capture(*git, "add", ".gitignore", "a.go", cwd=source)
        runner.capture(*git, "commit", "-q", "-m", "a", cwd=source)
        (source / "new.go").write_text("package a\n")
        (source / "mockgen_tmp.go").write_text("package a\n")
        (source / "staged_tmp.go").write_text("package a\n")
        runner.capture(*git, "add", "-f", "staged_tmp.go", cwd=source)
        recorded = runner.tree_paths(source, runner.source_identity(source)["tree"])
        runner.check_build_sources({source / "a.go", source / "new.go"}, recorded)
        for name in ("mockgen_tmp.go", "staged_tmp.go"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, name):
                runner.check_build_sources({source / "a.go", source / name}, recorded)


class RunTests(unittest.TestCase):
    def test_source_is_snapshot_before_in_tree_output(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        source = Path(directory.name)
        git = ("git", "-c", "user.name=t", "-c", "user.email=t@example.invalid")
        runner.capture(*git, "init", "-q", cwd=source)
        (source / "a.go").write_text("package a\n")
        runner.capture(*git, "add", "a.go", cwd=source)
        runner.capture(*git, "commit", "-q", "-m", "a", cwd=source)

        def build(_, toolchain, output, profile):
            binary = output / "native-darwin.test"
            binary.write_text("binary")
            return binary, {"go": "go1.27.4", "toolchain": toolchain, "mode": dict(profile.build), "binary_sha256": "c" * 64}

        def run_case(_, name, output, identity, timeout, profile):
            return {"case": name, "command": runner.command_for("native-darwin.test", name, profile), "exit": 0, "seconds": 0.01, "record": record_for(name)}, None

        native = {"system": "Darwin", "machine": "arm64", "proc_translated": "0", "product_version": "27.2.1", "build_version": "26B131", "kernel": "k", "cpu": "c"}
        originals = runner.native_identity, runner.build, runner.run_case
        runner.native_identity, runner.build, runner.run_case = (lambda: dict(native)), build, run_case
        self.addCleanup(setattr, runner, "native_identity", originals[0])
        self.addCleanup(setattr, runner, "build", originals[1])
        self.addCleanup(setattr, runner, "run_case", originals[2])
        selected = runner.selected_sources
        runner.selected_sources = lambda source, toolchain, profile: {source / "a.go"}
        self.addCleanup(setattr, runner, "selected_sources", selected)
        which = runner.shutil.which
        runner.shutil.which = lambda tool: f"/usr/bin/{tool}"
        self.addCleanup(setattr, runner.shutil, "which", which)
        results, failure = runner.run(source, source / "results", "local", 1)
        self.assertIsNone(failure)
        self.assertTrue(results["source"]["clean"], "the in-tree output is not source")
        runner.validate_results(json.loads((source / "results" / "results.json").read_text()))
        results, failure = runner.run(source, source / "pressure", "local", 1, PRESSURE)
        self.assertIsNone(failure)
        self.assertEqual(["socket-pressure"], [instance["case"] for instance in results["instances"]])
        runner.validate_results(json.loads((source / "pressure" / "results.json").read_text()), "pressure")


class ResultsTests(unittest.TestCase):
    def results(self, profile=runner.SCALAR):
        return {
            "schema": runner.RESULTS_SCHEMA,
            "profile": profile.name,
            "source": {"commit": "a" * 40, "tree": "b" * 40, "head_tree": "b" * 40, "clean": True},
            "build": {"go": "go1.27.4", "toolchain": "local", "mode": dict(profile.build), "binary_sha256": "c" * 64},
            "identity": {
                **IDENTITY, "system": "Darwin", "machine": "arm64", "proc_translated": "0",
                "product_version": "27.2.1", "build_version": "26B131", "kernel": "Darwin 27.2.0 arm64", "cpu": "Apple M4 Max",
            },
            "instances": [{"case": name, "command": runner.command_for("native-darwin.test", name, profile), "exit": 0, "seconds": 0.01, "failure": None, "record": record_for(name)} for name in profile.cases],
            "status": {"cases": len(profile.cases), "status": "pass", "support_receipt": False},
        }

    def test_readback_accepts_a_complete_run(self):
        runner.validate_results(self.results())
        runner.validate_results(self.results(PRESSURE), "pressure")
        explicit = self.results()
        explicit["build"]["toolchain"] = "go1.27.4"
        runner.validate_results(explicit)

    def test_readback_rejects_incomplete_or_failed_runs(self):
        missing = self.results()
        missing["instances"].pop()
        failed = self.results()
        failed["instances"][0]["failure"] = "exit 1"
        unstated = self.results()
        del unstated["status"]
        translated = self.results()
        translated["identity"]["proc_translated"] = "1"
        wrong_record = self.results()
        wrong_record["instances"][1]["record"] = record_for("ipv4")
        unsourced = self.results()
        del unsourced["source"]["tree"]
        other_build = self.results()
        other_build["build"]["go"] = "go1.26.11"
        misstated = self.results()
        misstated["source"]["tree"] = "d" * 40
        unidentified = self.results()
        del unidentified["identity"]["build_version"]
        selector = self.results()
        selector["build"]["toolchain"] = "go1.26.11"
        linux = self.results()
        linux["identity"]["goos"] = "linux"
        for instance in linux["instances"]:
            instance["record"]["goos"] = "linux"
        boolean_exit = self.results()
        boolean_exit["instances"][2]["exit"] = False
        numeric_support = self.results()
        numeric_support["status"]["support_receipt"] = 0
        float_cases = self.results()
        float_cases["status"]["cases"] = float(len(runner.CASES))
        unknown_field = self.results()
        unknown_field["build"]["extra"] = 1
        untagged = self.results(PRESSURE)
        untagged["build"]["mode"] = dict(runner.BUILD)
        relabeled = self.results(PRESSURE)
        relabeled["profile"] = "scalar"
        recounted = self.results(PRESSURE)
        recounted["status"]["cases"] = len(runner.CASES)
        other_selector = self.results(PRESSURE)
        other_selector["instances"][0]["command"] = runner.command_for("native-darwin.test", "socket-pressure")
        cases = (("untagged", untagged), ("relabeled", relabeled), ("recounted", recounted), ("pressure selector", other_selector), ("selector", selector), ("linux", linux), ("boolean exit", boolean_exit), ("unknown field", unknown_field), ("numeric support", numeric_support), ("float cases", float_cases), ("misstated clean", misstated), ("unidentified", unidentified), ("missing", missing), ("failed", failed), ("unstated", unstated), ("translated", translated), ("wrong record", wrong_record), ("unsourced", unsourced), ("other build", other_build))
        for name, results in cases:
            with self.subTest(name=name), self.assertRaises(ValueError):
                runner.validate_results(results)


BLOCKED = runner.PROFILES["blocked-writer"]
EXPIRED = "expired-before-dispatch-successor"
PROTECTED = "bbr-protected-close-join"
TRIGGER = {
    "evidence": "native-traversal", "send_buffer": 4096, "control_bytes": 12, "payload_bytes": 4096, "positive_control": "ECT(0)", "poller_witness": True,
    "injected": 0, "traced": False, "result": "deadline-exceeded", "uncertain": 1, "native_return_after_deadline_ms": 0.41,
}
CLAIM = {**TRIGGER, "native_calls": 2, "deadline_preserved": True, "deadline_reset": True, "native_returned": True}
# What the Go fixture records for each blocked-writer case on a passing run.
BLOCKED_FACTS = {
    "first-send-eperm": {
        "evidence": "simulated", "injected": 2, "first_send_retry": "accepted", "retry_delivered": True,
        "later_send": "uncertain-eperm", "faulted": False,
    },
    "constructed-segmentation-prefix": {
        "evidence": "constructed", "segments": 3, "whole_accepted": 3, "whole_delivered": 3, "prefix_injected": "EAGAIN",
        "prefix_accepted": 1, "prefix_uncertain": 1, "prefix_unsubmitted": 1, "prefix_delivered": 1,
    },
    "scalar-emsgsize": {
        "evidence": "native-size-feedback", "send_buffer": 4096, "payload_bytes": 4097, "errno": "EMSGSIZE", "unsubmitted": 1,
        "backpressure": False, "injected": 0, "successor_delivered": True, "faulted": False,
    },
    "expired-before-dispatch-successor": {
        "evidence": "expired-claim-unsubmitted", "positive_control": "ECT(0)", "expired_claim": 1, "expired_registration": 2,
        "expired_during": "deadline-setup", "expired_native_calls": 0, "expired_deadline_preserved": True, "expired_deadline_reset": True,
        "expired_result": "deadline-exceeded", "expired_accepted": 0, "expired_uncertain": 0, "expired_unsubmitted": 1,
        "successor_claim": 2, "successor_registration": 3, "successor_native_calls": 1, "successor_deadline_preserved": True,
        "successor_accepted": 1, "successor_delivered": True, "injected": 0, "traced": False, "faulted": False,
    },
    "eagain-to-deadline": {**CLAIM, "publication_ms": 0.02, "successor_deadline_preserved": True, "successor_delivered": True, "faulted": False},
    "queued-expiry": {
        **CLAIM, "queued_result": "deadline-exceeded", "queued_unsubmitted": 1, "queued_claimed": False,
        "queued_before_current_deadline": True, "writer_waiting_at_queued_expiry": True, "queued_expiry_ms": 0.3,
        "queued_publication_ms": 0.05,
    },
    "active-close-join": {
        **TRIGGER, "request_deadline_preserved": True, "reset_observed_by_caller_write": True, "close_returned_while_borrowed": True, "canceled_wait": "canceled", "returned_after_close_began": True,
        "joined_after_return": True, "transport_write_after_join": "closed", "caller_write_delivered": True, "close_to_join_ms": 180.5,
    },
    "bbr-protected-close-join": {
        **CLAIM, "send_buffer": 1200, "control_bytes": 16, "payload_bytes": 1200, "native_calls": 1,
        "controller": "bbrv3", "bbr_credit": True, "protection_plan": True, "protected_by_writer": True,
        "native_ciphertext_opened": True, "control_opened": True, "borrowed_in_call": True, "close_returned_while_borrowed": True,
        "borrowed_at_native_return": True, "borrowed_at_fence": True, "lifetime": "borrowed-through-fence", "released_at_join": True,
        "joined_after_return": True, "successor_delivered": True, "faulted": False, "close_to_join_ms": 199.6,
    },
}


def blocked_record(name, **changes):
    return {"schema": runner.SCHEMA, "case": name, "go": "go1.27.4", "goos": "darwin", "goarch": "arm64", "facts": {**BLOCKED_FACTS[name], **changes}}


class BlockedWriterProfileTests(unittest.TestCase):
    def test_profile_selects_its_test_cases_and_tagged_build(self):
        self.assertEqual(tuple(BLOCKED_FACTS), BLOCKED.cases)
        self.assertEqual("-buildvcs=false -tags=nativequal", BLOCKED.build["GOFLAGS"])
        self.assertNotIn("nativequal", runner.SCALAR.build["GOFLAGS"], "ordinary selection never builds the traversal cases")
        self.assertIn(f"-test.run=^{runner.BLOCKED_TEST}$/^queued-expiry$", runner.command_for("bin", "queued-expiry", BLOCKED))
        output = f"--- PASS: {runner.BLOCKED_TEST} (0.20s)\n    --- PASS: {runner.BLOCKED_TEST}/queued-expiry (0.20s)\nPASS\n"
        runner.check_output("queued-expiry", output, BLOCKED)
        with self.assertRaisesRegex(ValueError, "exactly once"):
            runner.check_output("queued-expiry", output, runner.SCALAR)

    def test_an_untagged_build_cannot_pass_a_traversal_case(self):
        # Without the tag the case is not registered: the test passes, the case does not.
        output = f"=== RUN   {runner.BLOCKED_TEST}\n--- PASS: {runner.BLOCKED_TEST} (0.00s)\nPASS\n"
        with self.assertRaisesRegex(ValueError, "exactly once"):
            runner.check_output("eagain-to-deadline", output, BLOCKED)

    def test_each_case_once_per_profile(self):
        runner.check_accounting(list(BLOCKED.cases), BLOCKED)
        self.assertEqual(8, len(BLOCKED.cases), "D15 A and D13 A: X2 expects eight cases")
        with self.assertRaisesRegex(ValueError, "missing.*expired-before-dispatch-successor"):
            runner.check_accounting([name for name in BLOCKED.cases if name != EXPIRED], BLOCKED)
        with self.assertRaisesRegex(ValueError, "duplicate.*expired-before-dispatch-successor"):
            runner.check_accounting([*BLOCKED.cases, EXPIRED], BLOCKED)
        with self.assertRaisesRegex(ValueError, "missing.*active-close-join"):
            runner.check_accounting([name for name in BLOCKED.cases if name != "active-close-join"], BLOCKED)
        with self.assertRaisesRegex(ValueError, "missing.*bbr-protected-close-join"):
            runner.check_accounting([name for name in BLOCKED.cases if name != PROTECTED], BLOCKED)
        with self.assertRaisesRegex(ValueError, "duplicate.*bbr-protected-close-join"):
            runner.check_accounting([*BLOCKED.cases, PROTECTED], BLOCKED)
        with self.assertRaisesRegex(ValueError, "unknown.*ipv4"):
            runner.check_accounting([*BLOCKED.cases, "ipv4"], BLOCKED)
        with self.assertRaisesRegex(ValueError, "not a blocked-writer case"):
            runner.check_record("ipv4", IDENTITY, record_for("ipv4"), BLOCKED)

    def test_every_case_accepts_its_record(self):
        for name in BLOCKED.cases:
            with self.subTest(name=name):
                runner.check_record(name, IDENTITY, blocked_record(name), BLOCKED)


class BlockedWriterClassificationTests(unittest.TestCase):
    def refused(self, name, pattern, **changes):
        with self.assertRaisesRegex(ValueError, pattern):
            runner.check_record(name, IDENTITY, blocked_record(name, **changes), BLOCKED)

    def test_an_absent_stack_witness_is_not_traversal(self):
        for name in runner.TRAVERSAL_CASES:
            with self.subTest(name=name):
                self.refused(name, "no-witness is not native traversal", evidence="no-witness")
                self.refused(name, "poller_witness", poller_witness=False)

    def test_expiry_before_dispatch_is_not_a_blocked_native_call(self):
        for name in runner.TRAVERSAL_CASES:
            with self.subTest(name=name):
                self.refused(name, "expired-before-dispatch is not native traversal", evidence="expired-before-dispatch")
        self.refused("queued-expiry", "native_calls", native_calls=0)

    def test_a_missing_native_return_is_refused(self):
        self.refused("eagain-to-deadline", "missing-native-return is not native traversal", evidence="missing-native-return")
        self.refused("queued-expiry", "native_returned", native_returned=False)
        self.refused("active-close-join", "native_return_after_deadline_ms", native_return_after_deadline_ms=-1.0)

    def test_a_final_reset_failure_is_refused(self):
        self.refused("eagain-to-deadline", "reset-failure is not native traversal", evidence="reset-failure")
        self.refused("queued-expiry", "deadline_reset", deadline_reset=False)

    def test_injected_or_stale_observations_are_never_traversal(self):
        self.refused("eagain-to-deadline", "simulated is not native traversal", evidence="simulated")
        self.refused("eagain-to-deadline", "injected", injected=1)
        self.refused("queued-expiry", "stale-deadline is not native traversal", evidence="stale-deadline")
        self.refused("queued-expiry", "deadline_preserved", deadline_preserved=False)
        self.refused("active-close-join", "unknown class", evidence="native")
        self.refused("eagain-to-deadline", "traced", traced=True)

    def test_separately_classified_cases_keep_their_class(self):
        self.refused("first-send-eperm", "evidence", evidence="native-traversal")
        self.refused("constructed-segmentation-prefix", "evidence", evidence="native")
        self.refused("scalar-emsgsize", "backpressure", backpressure=True)
        self.refused("scalar-emsgsize", "payload_bytes", payload_bytes=4096)
        self.refused("eagain-to-deadline", "payload_bytes", payload_bytes=4097)
        self.refused("queued-expiry", "control_bytes", control_bytes=4096)
        self.refused("queued-expiry", "queued_claimed", queued_claimed=True)
        self.refused("active-close-join", "canceled_wait", canceled_wait="joined")
        self.refused("active-close-join", "joined_after_return", joined_after_return=False)
        self.refused("active-close-join", "request_deadline_preserved", request_deadline_preserved=False)
        self.refused("active-close-join", "reset_observed_by_caller_write", reset_observed_by_caller_write=False)
        self.refused("active-close-join", "positive_control", positive_control="CE")

    def test_a_malformed_class_is_a_case_failure(self):
        for evidence in (["native-traversal"], {"class": "native-traversal"}, None):
            with self.subTest(evidence=evidence):
                self.refused("queued-expiry", "not a class name", evidence=evidence)

    def test_bool_is_not_a_count_or_duration(self):
        self.refused("eagain-to-deadline", "send_buffer", send_buffer=True)
        self.refused("eagain-to-deadline", "publication_ms", publication_ms=True)
        self.refused("queued-expiry", "queued_publication_ms", queued_publication_ms=True)
        self.refused("scalar-emsgsize", "send_buffer", send_buffer=60000)

    def test_queued_expiry_needs_both_timing_facts(self):
        # The expiry is timed from the endpoint's decision and the collection delay
        # is its own fact, so a record lacking either is refused.
        for fact in ("queued_expiry_ms", "queued_publication_ms"):
            with self.subTest(fact=fact):
                record = blocked_record("queued-expiry")
                del record["facts"][fact]
                with self.assertRaisesRegex(ValueError, "queued-expiry: facts"):
                    runner.check_record("queued-expiry", IDENTITY, record, BLOCKED)


class BlockedWriterExpiredClaimTests(unittest.TestCase):
    """MP-MAC #1571 (D15 A): the expired claim and its successor."""

    def refused(self, pattern, **changes):
        with self.assertRaisesRegex(ValueError, pattern):
            runner.check_record(EXPIRED, IDENTITY, blocked_record(EXPIRED, **changes), BLOCKED)

    def test_the_expired_claim_made_no_native_call(self):
        self.refused("expired_native_calls", expired_native_calls=1)

    def test_nothing_was_injected_or_traced(self):
        self.refused("injected", injected=1)
        self.refused("traced", traced=True)

    def test_the_expired_claim_submitted_nothing(self):
        self.refused("expired_accepted", expired_accepted=1)
        self.refused("expired_uncertain", expired_uncertain=1)
        self.refused("expired_unsubmitted", expired_unsubmitted=0)
        self.refused("expired_result", expired_result="accepted")

    def test_the_successor_was_delivered_natively(self):
        self.refused("successor_delivered", successor_delivered=False)
        self.refused("successor_native_calls", successor_native_calls=0)
        self.refused("successor_accepted", successor_accepted=0)
        record = blocked_record(EXPIRED)
        del record["facts"]["successor_delivered"]
        with self.assertRaisesRegex(ValueError, f"{EXPIRED}: facts"):
            runner.check_record(EXPIRED, IDENTITY, record, BLOCKED)

    def test_the_failure_class_is_refused(self):
        self.refused("'expired-before-dispatch' is the traversal failure class; the expired claim's own class is", evidence="expired-before-dispatch")
        self.refused("'native-traversal' is another class; the expired claim's own class is", evidence="native-traversal")
        self.refused("not a class name", evidence=None)

    def test_both_claims_are_identified(self):
        self.refused("expired_claim", expired_claim=2)
        self.refused("successor_claim", successor_claim=1)
        self.refused("expired_registration", expired_registration=3)
        self.refused("expired_during", expired_during="claim")
        self.refused("expired_deadline_reset", expired_deadline_reset=False)

    def test_no_poller_fields(self):
        for fact, value in (("poller_witness", True), ("native_return_after_deadline_ms", 0.4)):
            with self.subTest(fact=fact):
                self.refused(f"{EXPIRED}: facts", **{fact: value})


class BlockedWriterProtectedMemberTests(unittest.TestCase):
    """MP-MAC #1570 (D13 A, B8): a BBR protected member's storage stays borrowed
    through the native return and the final fence, across an active close."""

    def refused(self, pattern, **changes):
        with self.assertRaisesRegex(ValueError, pattern):
            runner.check_record(PROTECTED, IDENTITY, blocked_record(PROTECTED, **changes), BLOCKED)

    def test_it_is_a_traversal_case(self):
        self.assertIn(PROTECTED, runner.TRAVERSAL_CASES)
        for evidence in ("simulated", "no-witness", "expired-before-dispatch", "missing-native-return", "reset-failure", "stale-deadline"):
            with self.subTest(evidence=evidence):
                self.refused(f"{evidence} is not native traversal", evidence=evidence)
        self.refused("unknown class", evidence="native")
        self.refused("poller_witness", poller_witness=False)

    def test_nothing_was_injected_or_traced(self):
        self.refused("injected", injected=1)
        self.refused("traced", traced=True)

    def test_the_recorder_saw_the_claim(self):
        self.refused("native_calls", native_calls=0)
        self.refused("deadline_preserved", deadline_preserved=False)
        self.refused("deadline_reset", deadline_reset=False)
        self.refused("native_returned", native_returned=False)

    def test_each_borrow_sample_is_required(self):
        for fact in ("borrowed_in_call", "close_returned_while_borrowed", "borrowed_at_native_return", "borrowed_at_fence", "released_at_join", "joined_after_return"):
            with self.subTest(fact=fact):
                self.refused(fact, **{fact: False})

    def test_every_other_lifetime_is_refused_by_name(self):
        for lifetime in ("unprotected", "not-bbr", "plaintext-at-native-call", "released-during-call", "released-at-return", "released-before-fence", "not-released"):
            with self.subTest(lifetime=lifetime):
                self.refused(f"{PROTECTED}: lifetime {lifetime} is not borrowed-through-fence", lifetime=lifetime)
        self.refused("unknown lifetime 'borrowed'", lifetime="borrowed")
        self.refused("lifetime .* is not a class name", lifetime=None)
        self.refused("lifetime .* is not a class name", lifetime=["borrowed-through-fence"])

    def test_the_member_was_a_protected_bbr_member(self):
        self.refused("protection_plan", protection_plan=False)
        self.refused("protected_by_writer", protected_by_writer=False)
        self.refused("native_ciphertext_opened", native_ciphertext_opened=False)
        self.refused("control_opened", control_opened=False)
        self.refused("controller", controller="reno")
        self.refused("bbr_credit", bbr_credit=False)

    def test_the_trigger_is_exactly_the_send_buffer(self):
        self.refused("payload_bytes", payload_bytes=1201)
        self.refused("control_bytes", control_bytes=1200)
        self.refused("successor_delivered", successor_delivered=False)
        self.refused("faulted", faulted=True)
        self.refused("close_to_join_ms", close_to_join_ms=True)

    def test_a_missing_or_extra_fact_is_refused(self):
        for fact in ("borrowed_at_fence", "lifetime", "close_to_join_ms"):
            with self.subTest(fact=fact):
                record = blocked_record(PROTECTED)
                del record["facts"][fact]
                with self.assertRaisesRegex(ValueError, f"{PROTECTED}: facts"):
                    runner.check_record(PROTECTED, IDENTITY, record, BLOCKED)
        self.refused(f"{PROTECTED}: facts", canceled_wait="canceled")


class BlockedWriterRunCaseTests(unittest.TestCase):
    def test_interrupted_observation_is_killed_and_claims_nothing(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        marker = Path(directory.name) / "observer.pid"
        # The case wrote its record, then its observation hung with a child observer.
        body = (
            f"json.dump({blocked_record('queued-expiry')!r}, open(os.environ['{runner.RECORD_ENV}'], 'w'))\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            f"open({str(marker)!r}, 'w').write(str(child.pid))\n"
            "time.sleep(60)"
        )
        binary = fake_binary(directory.name, body)
        instance, failure = runner.run_case(binary, "queued-expiry", Path(directory.name) / "out", IDENTITY, 1, BLOCKED)
        self.assertRegex(failure, "timeout")
        self.assertIsNone(instance["record"], "a record from an interrupted case is not read")
        observer = int(marker.read_text())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(observer, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            self.fail("the case's observer survived the timeout")


class BlockedWriterResultsTests(unittest.TestCase):
    def results(self):
        results = ResultsTests.results(self)
        results["profile"] = "blocked-writer"
        results["build"]["mode"] = dict(BLOCKED.build)
        results["instances"] = [{"case": name, "command": runner.command_for("native-darwin.test", name, BLOCKED), "exit": 0, "seconds": 0.2, "failure": None, "record": blocked_record(name)} for name in BLOCKED.cases]
        results["status"]["cases"] = len(BLOCKED.cases)
        return results

    def instance(self, results, name):
        return next(instance for instance in results["instances"] if instance["case"] == name)

    def test_readback_accepts_a_complete_run(self):
        results = self.results()
        self.assertEqual(8, len(results["instances"]))
        runner.validate_results(results)

    def test_readback_refuses_a_seven_case_run(self):
        results = self.results()
        results["instances"] = [instance for instance in results["instances"] if instance["case"] != PROTECTED]
        results["status"]["cases"] = 7
        with self.assertRaisesRegex(ValueError, "missing.*bbr-protected-close-join"):
            runner.validate_results(results)

    def test_readback_binds_the_profile(self):
        untagged = self.results()
        untagged["build"]["mode"] = dict(runner.BUILD)
        scalar = self.results()
        scalar["profile"] = "scalar"
        unknown = self.results()
        unknown["profile"] = "unknown"
        unstated = self.results()
        del unstated["profile"]
        unwitnessed = self.results()
        self.instance(unwitnessed, "eagain-to-deadline")["record"]["facts"]["evidence"] = "no-witness"
        other_selector = self.results()
        self.instance(other_selector, "queued-expiry")["command"] = runner.command_for("native-darwin.test", "active-close-join", BLOCKED)
        no_command = self.results()
        no_command["instances"][0]["command"] = []
        cases = (("untagged", untagged), ("scalar", scalar), ("unknown", unknown), ("unstated", unstated), ("unwitnessed", unwitnessed), ("other selector", other_selector), ("no command", no_command))
        for name, results in cases:
            with self.subTest(name=name), self.assertRaises(ValueError):
                runner.validate_results(results)

    def test_a_requested_profile_must_be_the_recorded_one(self):
        runner.validate_results(self.results(), "blocked-writer")
        with self.assertRaisesRegex(ValueError, "requested 'scalar'"):
            runner.validate_results(self.results(), "scalar")
        with self.assertRaisesRegex(ValueError, "requested 'blocked-writer'"):
            runner.validate_results(ResultsTests.results(self), "blocked-writer")


class RaceSelectionTests(unittest.TestCase):
    def test_selected_race_tests_exist_once_in_the_root_package(self):
        root = Path(__file__).resolve().parents[2]
        sources = "".join(path.read_text() for path in sorted(root.glob("*_test.go")))
        for name in runner.RACE_TESTS:
            with self.subTest(name=name):
                self.assertEqual(1, sources.count(f"func {name}(t *testing.T)"))
        command = runner.race_command()
        self.assertEqual(["go", "test", "-race", "-count=1"], command[:4])
        self.assertEqual(f"-run=^({'|'.join(runner.RACE_TESTS)})$", command[4])

    def test_the_printed_race_command_is_one_shell_command(self):
        printed = subprocess.run([sys.executable, "-B", str(Path(__file__).with_name("native_darwin.py")), "--print-race-command"], check=True, capture_output=True, text=True).stdout
        subprocess.run(["/bin/sh", "-n"], input=printed, check=True, text=True)
        # The shell's own word splitting of the printed line yields the argument vector.
        words = subprocess.run(["/bin/sh", "-c", f"set -- {printed.strip()}; for word; do printf '%s\\0' \"$word\"; done"], check=True, capture_output=True, text=True).stdout
        self.assertEqual(runner.race_command(), words.split("\0")[:-1])


if __name__ == "__main__":
    unittest.main()
