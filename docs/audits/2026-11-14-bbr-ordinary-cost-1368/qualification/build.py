#!/usr/bin/env python3
"""Verify the frozen measurement bundle, build it, and record binary identity."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True, help="fresh extraction of the bundle's source.tar")
    args = parser.parse_args()
    bundle, source = args.bundle.resolve(), args.source.resolve()
    manifest = json.loads((bundle / "manifest.json").read_text())
    if digest(bundle / "source.tar") != manifest["source_archive_sha256"]:
        raise ValueError("source archive changed")
    for name, key in (("ordinary_cost_b5.py", "historical_driver_sha256"),
                      ("overlay.patch", "overlay_diff_sha256"), ("build.py", "build_helper_sha256")):
        if digest(bundle / name) != manifest[key]:
            raise ValueError(f"bundle helper changed: {name}")
    actual = {str(path.relative_to(source)) for path in source.rglob("*") if path.is_file() or path.is_symlink()}
    if actual != set(manifest["source_files"]):
        raise ValueError("source file inventory differs from the pinned archive")
    for name, expected in manifest["source_files"].items():
        path = source / name
        if expected["kind"] == "symlink":
            if not path.is_symlink() or os.readlink(path) != expected["target"]:
                raise ValueError(f"source symlink changed: {name}")
        elif path.is_symlink() or digest(path) != expected["sha256"]:
            raise ValueError(f"source file changed: {name}")
    replace = {}
    for name, hashes in manifest["overlay_files"].items():
        original, replacement = source / name, bundle / "replacements" / name
        if digest(original) != hashes["original_sha256"] or digest(replacement) != hashes["replacement_sha256"]:
            raise ValueError(f"overlay identity mismatch: {name}")
        replace[str(original)] = str(replacement)
    overlay = bundle / "overlay.json"
    overlay.write_text(json.dumps({"Replace": replace}, indent=2) + "\n")
    binary = bundle / "ordinarycost.test"
    if binary.exists() or (bundle / "build-receipt.json").exists():
        raise ValueError("a build already exists; preserve it and prepare a new bundle")
    version = subprocess.check_output(["go", "version"], text=True).strip()
    if version != f"go version {manifest['go_version']} linux/amd64":
        raise ValueError(f"build requires native pinned Linux amd64 toolchain, got {version}")
    env = os.environ.copy()
    env.update(manifest["build_environment"], GOFLAGS="", GOWORK="off")
    command = ["go", "test", f"-overlay={overlay}", "-tags", "ordinarycost", "-c", "-o", str(binary), "."]
    receipt = {"product_sha": manifest["product_sha"], "manifest_sha256": digest(bundle / "manifest.json"),
               "overlay_sha256": digest(overlay), "command": command, "working_directory": str(source),
               "environment": {key: env[key] for key in (*manifest["build_environment"], "GOFLAGS", "GOWORK")},
               "go_version": version, "public_enablement": False}
    with (bundle / "build.log").open("w") as log:
        result = subprocess.run(command, cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT)
    receipt["exit_code"] = result.returncode
    if result.returncode == 0:
        receipt["binary_sha256"] = digest(binary)
        receipt["binary_build_info"] = subprocess.check_output(["go", "version", "-m", str(binary)], text=True)
    (bundle / "build-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(bundle / "build-receipt.json")
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
