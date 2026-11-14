"""Apparatus checks; these tests never build or launch a native peer."""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
SOURCE = "7721bd07dcce00e2734fa6b4ef3b0a3fb402ed2b"


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare, builder, runner = load("prepare"), load("build"), load("run_b5")


class OverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = Path(subprocess.check_output(["git", "-C", str(HERE), "rev-parse", "--show-toplevel"], text=True).strip())
        cls.originals = {name: prepare.git(cls.repo, "show", f"{SOURCE}:{name}") for name in prepare.EXPECTED}

    def test_restored_fixture_preserves_historical_scenarios_without_private_selector(self):
        changed = prepare.replacements(self.originals)
        historical = prepare.git(self.repo, "show", f"{prepare.HISTORICAL_REVISION}:multipath_picoquic_matrix_test.go")
        fixture = changed["multipath_picoquic_matrix_test.go"]
        self.assertEqual(fixture, historical.replace(prepare.RETIRED_SELECTION.encode(), b"", 1))
        self.assertNotIn(b"multipathEvidence", fixture)
        self.assertEqual(set(changed), {"multipath_api.go", "multipath_picoquic_matrix_test.go"})
        self.assertIn(b'require.Equal(t, controller, s.conn.CongestionControlV1())', fixture)

    def test_changed_source_fails_closed(self):
        for name in self.originals:
            originals = self.originals | {name: self.originals[name] + b"\n"}
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "source hash"):
                prepare.replacements(originals)

    def test_driver_and_timeline_sources_are_frozen(self):
        historical = prepare.git(self.repo, "show", f"{prepare.HISTORICAL_REVISION}:interop/multipath/run.py")
        self.assertEqual((HERE / "run_b5.py").read_bytes(), historical)
        self.assertEqual(prepare.digest(historical), prepare.DRIVER_SHA256)
        for name, expected in prepare.UNCHANGED.items():
            data = prepare.git(self.repo, "show", f"{SOURCE}:{name}")
            self.assertEqual(prepare.digest(data), expected, name)
            self.assertEqual(data, prepare.git(self.repo, "show", f"{prepare.HISTORICAL_REVISION}:{name}"), name)


class DriverTests(unittest.TestCase):
    def write_cases(self, root):
        expected = runner.matrix_expected("bbrv3")
        for case in expected:
            _, scenario, role = case.split("/")
            directory = root / scenario / role
            directory.mkdir(parents=True)
            event = {"Action": "pass", "Package": runner.SMOKE_PACKAGE, "Test": case}
            (directory / "go-test.jsonl").write_text(json.dumps(event) + "\n")
            (directory / "result.json").write_text(json.dumps({"status": "pass", "executed": [case], "controller": "bbrv3", "identity": {"candidate": "a" * 40}}))
        return expected

    def test_six_case_inventory_and_original_timeouts(self):
        expected = [f"TestPicoquicMultipathMatrix/{scenario}/{role}" for scenario in prepare.SCENARIOS for role in ("client", "server")]
        self.assertEqual(expected, runner.matrix_expected("bbrv3"))
        for case in expected:
            _, scenario, role = case.split("/")
            command, selected = runner.matrix_invocation(scenario, role, Path("/bundle/peer-matrix.test"))
            self.assertEqual(selected, [case])
            self.assertIn("-test.timeout=90s", command)
            self.assertIn(f"-test.run=^TestPicoquicMultipathMatrix$/^{scenario}$/^{role}$", command)

    def test_missing_duplicate_skipped_and_extra_cases_fail(self):
        for failure in ("missing", "duplicate", "skip", "extra"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                expected = self.write_cases(root)
                path = root / "useful-transfer/client/go-test.jsonl"
                if failure == "missing":
                    path.unlink()
                elif failure == "duplicate":
                    path.write_text(path.read_text() * 2)
                elif failure == "skip":
                    path.write_text(json.dumps({"Action": "skip", "Package": runner.SMOKE_PACKAGE, "Test": expected[0]}) + "\n")
                else:
                    extra = root / "absent-negotiation/client"
                    extra.mkdir(parents=True)
                    (extra / "go-test.jsonl").write_text(path.read_text())
                with self.assertRaises(ValueError):
                    runner.check_matrix(root, "bbrv3")

    def test_controller_or_identity_mismatch_fails(self):
        for field, value in (("controller", "reno"), ("identity", {"candidate": "b" * 40})):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.write_cases(root)
                self.assertEqual(len(runner.check_matrix(root, "bbrv3")["executed"]), 6)
                path = root / "useful-transfer/client/result.json"
                result = json.loads(path.read_text())
                result[field] = value
                path.write_text(json.dumps(result))
                with self.assertRaises(ValueError):
                    runner.check_matrix(root, "bbrv3")


class BuildVerificationTests(unittest.TestCase):
    def test_source_helper_and_overlay_mutation_are_rejected(self):
        for target in ("source/main.go", "bundle/run_b5.py", "bundle/replacements/main.go", "source/extra.go"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source, bundle = root / "source", root / "bundle"
                source.mkdir()
                (bundle / "replacements").mkdir(parents=True)
                for name, contents in {"source/main.go": b"source", "bundle/source.tar": b"archive", "bundle/run_b5.py": b"driver",
                                       "bundle/overlay.patch": b"diff", "bundle/replacements/main.go": b"replacement"}.items():
                    (root / name).write_bytes(contents)
                manifest = {"source_archive_sha256": builder.digest(bundle / "source.tar"),
                            "bundle_files": {"run_b5.py": builder.digest(bundle / "run_b5.py")},
                            "overlay_diff_sha256": builder.digest(bundle / "overlay.patch"),
                            "source_files": {"main.go": {"kind": "file", "sha256": builder.digest(source / "main.go")}},
                            "overlay_files": {"main.go": {"original_sha256": builder.digest(source / "main.go"),
                                                           "replacement_sha256": builder.digest(bundle / "replacements/main.go")}}}
                self.assertEqual(builder.verify(bundle, source, manifest), {str(source / "main.go"): str(bundle / "replacements/main.go")})
                (root / target).write_bytes(b"changed")
                with self.assertRaises(ValueError):
                    builder.verify(bundle, source, manifest)


if __name__ == "__main__":
    unittest.main()
