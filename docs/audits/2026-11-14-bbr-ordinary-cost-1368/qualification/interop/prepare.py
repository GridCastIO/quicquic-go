#!/usr/bin/env python3
"""Freeze the existing six BBR interop cases with a measurement-only Go overlay."""

import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile


HISTORICAL_REVISION = "4e80d3cf4fa7454ffc3e2a46655afd5f81f86313"
DRIVER_SHA256 = "7de31bd73bfb026c7aa24989139fd38032c5caac730498f4967c3b5dde4c1990"
HISTORICAL_MATRIX_SHA256 = "270dbdd71a42e5622217b9fa33fc12c4a32d467a19e05b8f9e0a38bf8a227ccb"
EXPECTED = {
    "multipath_api.go": "3bad7b0f6c66e5e30e99088b12a1864f3be07b2cbee9a86914527b7580c86aca",
    "multipath_picoquic_matrix_test.go": "d81d1e4fc5b574bd4f0fcd5de03c916168fa2e02b53602a8268f411cd90f971b",
}
# These files own the unchanged scenario timeline, peer, build pins and oracles.
UNCHANGED = {
    "multipath_picoquic_oracle_test.go": "2fce160c13ed8b246b93dbf8c7c468d91ff608766b2a7bdf72d7396df7c2bd1c",
    "multipath_picoquic_trace_test.go": "212c47b95e434d27a96408e5b419347671a19f20b14eaa2bd4b0c07c26ba53f0",
    "multipath_picoquic_test.go": "9105ae50c1626291fa8c80b0db5c33523f077ff310a76bebfbf5548d1b07c033",
    "interop/multipath/peer.c": "ccd8f167f2c02aa5f347324abf13bfab713bbb826dbe4ec697cc8420eb3781e4",
    "interop/multipath/Dockerfile": "6f650d537c8b6925af37ab9a7f9fc5ed11038db1bd782e6a75de6ed961884fad",
    "interop/multipath/Dockerfile.dockerignore": "6c71c40c019b3651e8dfc38f8ef9e0321f1ed0c3ebf94edb3385e9c3136a854f",
}
SCENARIOS = ["useful-transfer", "abandon-reopen-late-feedback", "same-id-migration-rebinding"]
RETIRED_SELECTION = (
    "\t// B5's revalidation cells run BBR primary/backup through the evidence selection,\n"
    "\t// before B6 publishes the combination (#1044).\n"
    '\tconf.multipath.evidence = multipathEvidence{bbr: controller == "bbrv3"}\n'
)
CONTROLLER = '''// matrixController is the quic-go endpoint's controller: Reno for the R17 matrix, or BBR
// for B5's primary/backup revalidation of its useful-transfer, abandon/reopen and
// same-ID migration scenarios (#1044).
func matrixController(t *testing.T) string {
	t.Helper()
	switch controller := os.Getenv("QGF_MATRIX_CONTROLLER"); controller {
	case "", "reno":
		return "reno"
	case "bbrv3":
		return controller
	default:
		t.Fatalf("unknown QGF_MATRIX_CONTROLLER %q", controller)
		return ""
	}
}

'''
REPLACEMENTS = {
    "multipath_api.go": [(
        '\tif conf.CongestionControlV1() != "reno" {\n',
        '\tif conf.CongestionControlV1() != "reno" && conf.CongestionControlV1() != "bbrv3" {\n',
    )],
    "multipath_picoquic_matrix_test.go": [
        ("func newMatrixSession(t *testing.T, role string, negotiated, cidReceipt bool) *matrixSession {\n",
         CONTROLLER + "func newMatrixSession(t *testing.T, role string, negotiated, cidReceipt bool) *matrixSession {\n"),
        ('\trequire.NoError(t, conf.ConfigureMultipathV1(true, 2, "primary-backup"))\n',
         '\trequire.NoError(t, conf.ConfigureMultipathV1(true, 2, "primary-backup"))\n'
         '\tcontroller := matrixController(t)\n\trequire.NoError(t, conf.SetCongestionControlV1(controller))\n'),
        ('\tt.Cleanup(func() { s.conn.CloseWithError(0, "matrix cleanup") })\n',
         '\tt.Cleanup(func() { s.conn.CloseWithError(0, "matrix cleanup") })\n'
         '\trequire.Equal(t, controller, s.conn.CongestionControlV1())\n'),
    ],
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def replacements(originals):
    changed = {}
    for name, expected in EXPECTED.items():
        if digest(originals[name]) != expected:
            raise ValueError(f"{name}: unexpected source hash; inspect this apparatus explicitly")
        text = originals[name].decode()
        for before, after in REPLACEMENTS[name]:
            if text.count(before) != 1:
                raise ValueError(f"{name}: replacement snippet is not unique")
            text = text.replace(before, after, 1)
        changed[name] = text.encode()
    return changed


def prepare(repo, product_sha, output):
    if not re.fullmatch(r"[0-9a-f]{40}", product_sha):
        raise ValueError("product SHA must be a full lowercase commit SHA")
    if git(repo, "rev-parse", f"{product_sha}^{{commit}}").decode().strip() != product_sha:
        raise ValueError("product SHA did not resolve exactly")
    originals = {name: git(repo, "show", f"{product_sha}:{name}") for name in EXPECTED}
    changed = replacements(originals)
    historical = git(repo, "show", f"{HISTORICAL_REVISION}:multipath_picoquic_matrix_test.go")
    if digest(historical) != HISTORICAL_MATRIX_SHA256 or historical.count(RETIRED_SELECTION.encode()) != 1:
        raise ValueError("historical matrix identity changed")
    if changed["multipath_picoquic_matrix_test.go"] != historical.replace(RETIRED_SELECTION.encode(), b"", 1):
        raise ValueError("overlay differs from B5 beyond removal of retired private activation")
    for name, expected in UNCHANGED.items():
        current = git(repo, "show", f"{product_sha}:{name}")
        if digest(current) != expected or current != git(repo, "show", f"{HISTORICAL_REVISION}:{name}"):
            raise ValueError(f"scenario/peer source changed: {name}")
    here = Path(__file__).resolve().parent
    driver = (here / "run_b5.py").read_bytes()
    if digest(driver) != DRIVER_SHA256 or driver != git(repo, "show", f"{HISTORICAL_REVISION}:interop/multipath/run.py"):
        raise ValueError("historical driver is not byte-exact")
    output.mkdir(parents=True, exist_ok=False)
    (output / "replacements").mkdir()
    files, diff = {}, []
    for name, data in changed.items():
        (output / "replacements" / name).write_bytes(data)
        files[name] = {"original_sha256": digest(originals[name]), "replacement_sha256": digest(data)}
        diff.extend(difflib.unified_diff(originals[name].decode().splitlines(keepends=True), data.decode().splitlines(keepends=True),
                                       fromfile=f"product/{name}", tofile=f"measurement/{name}"))
    (output / "overlay.patch").write_text("".join(diff))
    archive = output / "source.tar"
    with archive.open("wb") as stream:
        subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", product_sha], stdout=stream, check=True)
    source_files = {}
    with tarfile.open(archive) as tar:
        for member in tar:
            if member.isfile():
                source_files[member.name] = {"kind": "file", "sha256": digest(tar.extractfile(member).read())}
            elif member.issym():
                source_files[member.name] = {"kind": "symlink", "target": member.linkname}
            elif not member.isdir():
                raise ValueError(f"unsupported archive member {member.name}")
    for name in ("build.py", "run_b5.py"):
        shutil.copyfile(here / name, output / name)
    (output / "peer.c").write_bytes(git(repo, "show", f"{product_sha}:interop/multipath/peer.c"))
    manifest = {
        "product_sha": product_sha,
        "product_tree": git(repo, "rev-parse", f"{product_sha}^{{tree}}").decode().strip(),
        "source_archive_sha256": digest(archive.read_bytes()), "source_files": source_files,
        "overlay_files": files, "overlay_diff_sha256": digest((output / "overlay.patch").read_bytes()),
        "historical_revision": HISTORICAL_REVISION, "historical_driver_path": "interop/multipath/run.py",
        "historical_matrix_sha256": HISTORICAL_MATRIX_SHA256, "unchanged_scenario_sources": UNCHANGED,
        "bundle_files": {name: digest((output / name).read_bytes()) for name in ("build.py", "run_b5.py", "peer.c")},
        "generator_sha256": digest(Path(__file__).read_bytes()),
        "build_command_template": ["go", "test", "-overlay=ABSOLUTE_OVERLAY_JSON", "-tags", "picoquic", "-c", "-o", "ABSOLUTE_BINARY", "."],
        "build_environment": {"GOOS": "linux", "GOARCH": "amd64", "CGO_ENABLED": "0", "GOAMD64": "v1", "GOEXPERIMENT": "", "GOTOOLCHAIN": "local", "GOENV": "off", "GOFLAGS": "", "GOWORK": "off"},
        "go_version": "go1.27.4", "public_enablement": False,
        "qualification": {"controller": "bbrv3", "scenarios": SCENARIOS, "roles": ["client", "server"],
                          "planned_observations": 6, "role_context_seconds": 30, "test_timeout_seconds": 90,
                          "driver_timeout_seconds": 120, "container_timeout_seconds": 150,
                          "zero_evidence": "separate mandatory hosted R17 job"},
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return output / "manifest.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--product-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.repo.resolve(), args.product_sha, args.output.resolve()))


if __name__ == "__main__":
    main()
