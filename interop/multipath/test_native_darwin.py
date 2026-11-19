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


def family_facts(name):
    return {
        "family": name, "granted_local": "[::]:5000", "peer": "127.0.0.1:6000", "inbound_source": "127.0.0.1:6000",
        "inbound_destination": runner.FAMILIES[name], "inbound_interface": 1, "inbound_ecn": "CE", "outbound_accepted": 1,
        "outbound_source": "127.0.0.1:5000", "outbound_ecn": "ECT(0)", "joined": True,
    }


def record_for(name, **changes):
    facts = family_facts(name) if name in runner.FAMILIES else dict(runner.FIXED_FACTS[name])
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

    def test_malformed_record_fails(self):
        for text in ("", "{", "[]", '"record"'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                runner.parse_record(text)


class AccountingTests(unittest.TestCase):
    def test_each_case_exactly_once(self):
        runner.check_accounting(list(runner.CASES))
        with self.assertRaisesRegex(ValueError, "missing.*ipv6"):
            runner.check_accounting([name for name in runner.CASES if name != "ipv6"])
        with self.assertRaisesRegex(ValueError, "duplicate.*ipv4"):
            runner.check_accounting([*runner.CASES, "ipv4"])
        with self.assertRaisesRegex(ValueError, "unknown.*ipv7"):
            runner.check_accounting([*runner.CASES, "ipv7"])


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


class ResultsTests(unittest.TestCase):
    def results(self):
        return {
            "schema": runner.RESULTS_SCHEMA,
            "source": {"commit": "a" * 40, "tree": "b" * 40, "head_tree": "b" * 40, "clean": True},
            "build": {"go": "go1.27.4", "toolchain": "local", "mode": dict(runner.BUILD), "binary_sha256": "c" * 64},
            "identity": {
                **IDENTITY, "system": "Darwin", "machine": "arm64", "proc_translated": "0",
                "product_version": "27.2.1", "build_version": "26B131", "kernel": "Darwin 27.2.0 arm64", "cpu": "Apple M4 Max",
            },
            "instances": [{"case": name, "exit": 0, "failure": None, "record": record_for(name)} for name in runner.CASES],
            "status": {"cases": len(runner.CASES), "status": "pass", "support_receipt": False},
        }

    def test_readback_accepts_a_complete_run(self):
        runner.validate_results(self.results())

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
        cases = (("misstated clean", misstated), ("unidentified", unidentified), ("missing", missing), ("failed", failed), ("unstated", unstated), ("translated", translated), ("wrong record", wrong_record), ("unsourced", unsourced), ("other build", other_build))
        for name, results in cases:
            with self.subTest(name=name), self.assertRaises(ValueError):
                runner.validate_results(results)


if __name__ == "__main__":
    unittest.main()
