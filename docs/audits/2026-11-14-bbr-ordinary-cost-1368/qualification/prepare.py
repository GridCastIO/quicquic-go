#!/usr/bin/env python3
"""Freeze an exact product source and measurement-only BBR qualification overlay."""

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
DRIVER_SHA256 = "37433087ea2b921bc47ed5603d52d7d55939347fbcab7208e62de3a6885f3d03"
EXPECTED = {
    "multipath_api.go": "3bad7b0f6c66e5e30e99088b12a1864f3be07b2cbee9a86914527b7580c86aca",
    "ordinary_cost_test.go": "748916b4f0a0999c76194430f2ebdf0301d3ee1b20b203033363e66cc5241912",
}
REPLACEMENTS = {
    "multipath_api.go": [(
        '\tif conf.CongestionControlV1() != "reno" {\n',
        '\tif conf.CongestionControlV1() != "reno" && conf.CongestionControlV1() != "bbrv3" {\n',
    )],
    "ordinary_cost_test.go": [
        ('\t\tif s.Cell == "stateless-pressure" {\n',
         '\t\tif s.Cell == "stateless-pressure" || s.Cell == "mixed-bulk" {\n'),
        ('\t// The BBR diagnostic exercises the endpoint grant without advertising multipath.\n'
         '\tlistener, err := tr.Listen(ordinaryCostServerTLS(), ordinaryCostConfig(t, spec.granted() && spec.controller() == "reno", spec.controller()))\n',
         '\t// Measurement-only: retain B5\'s granted-server multipath advertisement.\n'
         '\tlistener, err := tr.Listen(ordinaryCostServerTLS(), ordinaryCostConfig(t, spec.granted(), spec.controller()))\n'),
        ('type ordinaryCostServerConnResult struct {\n',
         'type ordinaryCostServerConnResult struct {\n\tController string `json:"controller"`\n'),
        ('type ordinaryCostFlowResult struct {\n',
         'type ordinaryCostFlowResult struct {\n\tController string `json:"controller"`\n'),
        ('\t\t\tLabel: label, Multipath: negotiated,\n',
         '\t\t\tLabel: label, Multipath: negotiated, Controller: entry.conn.CongestionControlV1(),\n'),
        ('\t\t\tLabel: flow.label, Series: series, UsefulBytes: useful,\n',
         '\t\t\tLabel: flow.label, Series: series, UsefulBytes: useful, Controller: flow.conn.CongestionControlV1(),\n'),
    ],
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def replacements(originals):
    changed = {}
    for name, expected in EXPECTED.items():
        original = originals[name]
        if digest(original) != expected:
            raise ValueError(f"{name}: unexpected source hash; inspect and revise this apparatus explicitly")
        text = original.decode()
        for before, after in REPLACEMENTS[name]:
            if text.count(before) != 1:
                raise ValueError(f"{name}: expected exactly one occurrence of {before!r}")
            text = text.replace(before, after, 1)
        changed[name] = text.encode()
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--product-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.product_sha):
        parser.error("--product-sha must be a full lowercase commit SHA")
    resolved = git(args.repo, "rev-parse", f"{args.product_sha}^{{commit}}").decode().strip()
    if resolved != args.product_sha:
        raise ValueError("product revision did not resolve to the supplied commit")
    originals = {name: git(args.repo, "show", f"{resolved}:{name}") for name in EXPECTED}
    changed = replacements(originals)
    here = Path(__file__).resolve().parent
    driver = (here / "ordinary_cost_b5.py").read_bytes()
    historical = git(args.repo, "show", f"{HISTORICAL_REVISION}:interop/multipath/ordinary_cost.py")
    if digest(driver) != DRIVER_SHA256 or driver != historical:
        raise ValueError("historical B5 driver is not byte-exact")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "replacements").mkdir()
    files = {}
    diff = []
    for name, data in changed.items():
        (output / "replacements" / name).write_bytes(data)
        files[name] = {"original_sha256": digest(originals[name]), "replacement_sha256": digest(data)}
        diff.extend(difflib.unified_diff(originals[name].decode().splitlines(keepends=True),
                                       data.decode().splitlines(keepends=True),
                                       fromfile=f"product/{name}", tofile=f"measurement/{name}"))
    (output / "overlay.patch").write_text("".join(diff))
    archive = output / "source.tar"
    with archive.open("wb") as stream:
        subprocess.run(["git", "-C", str(args.repo), "archive", "--format=tar", resolved], stdout=stream, check=True)
    source_files = {}
    with tarfile.open(archive) as tar:
        for member in tar:
            if member.isfile():
                source_files[member.name] = {"kind": "file", "sha256": digest(tar.extractfile(member).read())}
            elif member.issym():
                source_files[member.name] = {"kind": "symlink", "target": member.linkname}
            elif not member.isdir():
                raise ValueError(f"unsupported archive member {member.name}")
    shutil.copyfile(here / "build.py", output / "build.py")
    shutil.copyfile(here / "ordinary_cost_b5.py", output / "ordinary_cost_b5.py")
    manifest = {
        "product_sha": resolved,
        "product_tree": git(args.repo, "rev-parse", f"{resolved}^{{tree}}").decode().strip(),
        "source_archive_sha256": digest(archive.read_bytes()),
        "source_files": source_files,
        "overlay_files": files,
        "overlay_diff_sha256": digest((output / "overlay.patch").read_bytes()),
        "historical_driver_revision": HISTORICAL_REVISION,
        "historical_driver_path": "interop/multipath/ordinary_cost.py",
        "historical_driver_sha256": DRIVER_SHA256,
        "build_helper_sha256": digest((output / "build.py").read_bytes()),
        "generator_sha256": digest(Path(__file__).read_bytes()),
        "build_command_template": ["go", "test", "-overlay=ABSOLUTE_OVERLAY_JSON", "-tags", "ordinarycost", "-c", "-o", "ABSOLUTE_BINARY", "."],
        "build_environment": {"GOOS": "linux", "GOARCH": "amd64", "CGO_ENABLED": "0", "GOAMD64": "v1", "GOEXPERIMENT": "", "GOTOOLCHAIN": "local", "GOENV": "off"},
        "go_version": "go1.27.4",
        "qualification": {"controller": "bbrv3", "cells": ["mixed-bulk", "stateless-pressure"], "profiles": ["unregistered", "opted-in"], "rounds": 3, "planned_observations": 12},
        "public_enablement": False,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(output / "manifest.json")


if __name__ == "__main__":
    main()
