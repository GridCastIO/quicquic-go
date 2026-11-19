import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest


SPEC = importlib.util.spec_from_file_location("native_darwin", Path(__file__).with_name("native_darwin.py"))
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)

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


def contention_facts(participants=2, requests=3, members=2):
    """A complete observation, as the Go fixture records one, with no pressure wait."""
    lanes = []
    for participant in range(participants):
        for lane in runner.LANES:
            lanes.append({
                "participant": participant, "lane": lane, "offers": requests + 2, "admitted": requests, "refused": 2, "closed": 0,
                "results": requests, "withdrawn": 0, "accepted": requests * members, "uncertain": 0, "unsubmitted": 0, "failed": 0,
                "diagnostics": requests, "publication_lag_max_ns": 25000,
            })
    return {
        "status": "complete", "pressure_wait": "not-observed", "fault": "none", "diagnostics_dropped": 0,
        "load": {"participants": participants, "requests": requests, "members": members, "payload": 1200, "budget_ms": 1000, "window_ms": 10000},
        "writer": {
            "writes": participants * 3 * requests * members, "max_write_ns": 60000, "long_writes": 0, "deadline_waits": 0,
            "errors": {name: 0 for name in runner.ERROR_CLASSES},
        },
        "lanes": lanes, "occupancy_max": [4] * participants,
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
        runner.check_record(name, IDENTITY, record_for(name, facts=facts))

    def test_complete_observation_is_accepted(self):
        for name in runner.CONTENTION_CASES:
            with self.subTest(name=name):
                self.check(contention_facts(), name)

    def test_lane_accounting_must_add_up(self):
        for key, value in (("offers", 4), ("refused", 3), ("withdrawn", 1), ("accepted", 5), ("failed", 4), ("admitted", 4)):
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
            ("occupancy_max", lambda facts: facts["occupancy_max"].pop()),
            ("fault", lambda facts: facts.update(fault="unknown")),
            ("facts", lambda facts: facts.pop("writer")),
        )
        for pattern, change in changes:
            facts = contention_facts()
            change(facts)
            with self.subTest(pattern=pattern), self.assertRaisesRegex(ValueError, pattern):
                self.check(facts, "socket-pressure")

    def test_writer_observations_must_agree(self):
        for key, value in (("writes", 1), ("deadline_waits", 1), ("long_writes", 100)):
            facts = contention_facts()
            facts["writer"][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "writ"):
                self.check(facts, "socket-pressure")

    def test_status_and_pressure_follow_the_counts(self):
        # An observed wait stands in any status.
        observed = contention_facts()
        observed["writer"]["errors"]["deadline"] = observed["writer"]["deadline_waits"] = 1
        observed["lanes"][0].update(accepted=5, uncertain=1)
        observed["pressure_wait"] = "observed"
        self.check(observed, "socket-pressure")
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
        interrupted["lanes"][3].update(results=2, withdrawn=1, accepted=4, diagnostics=2)
        interrupted.update(status="interrupted", pressure_wait="unknown")
        self.check(interrupted, "socket-pressure")
        for facts, status, pressure in ((dropped, "incomplete-coverage", "not-observed"), (interrupted, "complete", "unknown"), (observed, "complete", "not-observed")):
            changed = {**facts, "status": status, "pressure_wait": pressure}
            with self.subTest(status=status, pressure=pressure), self.assertRaisesRegex(ValueError, "imply"):
                self.check(changed, "socket-pressure")

    def test_development_case_needs_complete_progress(self):
        interrupted = contention_facts()
        interrupted["lanes"][3].update(results=2, withdrawn=1, accepted=4, diagnostics=2)
        interrupted.update(status="interrupted", pressure_wait="unknown")
        faulted = {**contention_facts(), "fault": "overdue"}
        stalled = contention_facts()
        stalled["lanes"][2].update(accepted=0, unsubmitted=6, failed=3)
        for name, facts in (("interrupted", interrupted), ("faulted", faulted), ("stalled", stalled)):
            self.check(facts, "socket-pressure")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "development case"):
                self.check(facts)


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
        pressure = runner.PROFILES["pressure"]["cases"]
        runner.check_accounting(list(pressure), pressure)
        with self.assertRaisesRegex(ValueError, "unknown.*ipv4"):
            runner.check_accounting([*pressure, "ipv4"], pressure)
        with self.assertRaisesRegex(ValueError, "unknown.*socket-pressure"):
            runner.check_accounting([*runner.CASES, "socket-pressure"])
        self.assertIn("-tags=native_pressure", runner.PROFILES["pressure"]["mode"]["GOFLAGS"])
        self.assertNotIn("tags", runner.PROFILES["scalar"]["mode"]["GOFLAGS"], "default development builds never include the pressure mode")
        self.assertEqual(f"-test.run=^TestNativeDarwinPressure$/^socket-pressure$", runner.command_for("b", "socket-pressure", runner.PROFILES["pressure"]["test"])[1])


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
            return binary, {"go": "go1.27.4", "toolchain": toolchain, "mode": dict(runner.PROFILES[profile]["mode"]), "binary_sha256": "c" * 64}

        def run_case(_, name, output, identity, timeout, test):
            return {"case": name, "command": ["native-darwin.test"], "exit": 0, "seconds": 0.01, "record": record_for(name)}, None

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
        results, failure = runner.run(source, source / "pressure", "local", 1, "pressure")
        self.assertIsNone(failure)
        self.assertEqual(["socket-pressure"], [instance["case"] for instance in results["instances"]])
        runner.validate_results(json.loads((source / "pressure" / "results.json").read_text()))


class ResultsTests(unittest.TestCase):
    def results(self, profile="scalar"):
        cases = runner.PROFILES[profile]["cases"]
        return {
            "schema": runner.RESULTS_SCHEMA, "profile": profile,
            "source": {"commit": "a" * 40, "tree": "b" * 40, "head_tree": "b" * 40, "clean": True},
            "build": {"go": "go1.27.4", "toolchain": "local", "mode": dict(runner.PROFILES[profile]["mode"]), "binary_sha256": "c" * 64},
            "identity": {
                **IDENTITY, "system": "Darwin", "machine": "arm64", "proc_translated": "0",
                "product_version": "27.2.1", "build_version": "26B131", "kernel": "Darwin 27.2.0 arm64", "cpu": "Apple M4 Max",
            },
            "instances": [{"case": name, "command": ["native-darwin.test"], "exit": 0, "seconds": 0.01, "failure": None, "record": record_for(name)} for name in cases],
            "status": {"cases": len(cases), "status": "pass", "support_receipt": False},
        }

    def test_readback_accepts_a_complete_run(self):
        runner.validate_results(self.results())
        runner.validate_results(self.results("pressure"))
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
        untagged = self.results("pressure")
        untagged["build"]["mode"] = dict(runner.BUILD)
        unprofiled = self.results()
        del unprofiled["profile"]
        relabeled = self.results("pressure")
        relabeled["profile"] = "scalar"
        recounted = self.results("pressure")
        recounted["status"]["cases"] = len(runner.CASES)
        cases = (("untagged", untagged), ("unprofiled", unprofiled), ("relabeled", relabeled), ("recounted", recounted), ("selector", selector), ("linux", linux), ("boolean exit", boolean_exit), ("unknown field", unknown_field), ("numeric support", numeric_support), ("float cases", float_cases), ("misstated clean", misstated), ("unidentified", unidentified), ("missing", missing), ("failed", failed), ("unstated", unstated), ("translated", translated), ("wrong record", wrong_record), ("unsourced", unsourced), ("other build", other_build))
        for name, results in cases:
            with self.subTest(name=name), self.assertRaises(ValueError):
                runner.validate_results(results)


if __name__ == "__main__":
    unittest.main()
