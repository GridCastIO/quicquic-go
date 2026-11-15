#!/usr/bin/env python3
"""Verify the frozen interop overlay and build once inside the pinned peer image."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(bundle, source, manifest):
    if digest(bundle / "source.tar") != manifest["source_archive_sha256"]:
        raise ValueError("source archive changed")
    for name, expected in manifest["bundle_files"].items():
        if digest(bundle / name) != expected:
            raise ValueError(f"bundle helper changed: {name}")
    if digest(bundle / "overlay.patch") != manifest["overlay_diff_sha256"]:
        raise ValueError("overlay diff changed")
    actual = {str(path.relative_to(source)) for path in source.rglob("*") if path.is_file() or path.is_symlink()}
    if actual != set(manifest["source_files"]):
        raise ValueError("source file inventory differs from pinned archive")
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
    return replace


def build(bundle, source, peer):
    if (bundle / "peer-matrix.test").exists() or (bundle / "build-receipt.json").exists():
        raise ValueError("a build already exists; preserve it and prepare a new bundle")
    manifest = json.loads((bundle / "manifest.json").read_text())
    replace = verify(bundle, source, manifest)
    identity = {key: os.environ.get(key, "") for key in ("QGF_SOURCE_COMMIT", "QGF_SOURCE_TREE", "QGF_IMAGE_ID")}
    if identity["QGF_SOURCE_COMMIT"] != manifest["product_sha"] or identity["QGF_SOURCE_TREE"] != manifest["product_tree"]:
        raise ValueError("peer image source identity differs from product")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", identity["QGF_IMAGE_ID"]):
        raise ValueError("build requires exact QGF_IMAGE_ID from docker image inspect")
    if not peer.is_file() or not os.access(peer, os.X_OK):
        raise ValueError("missing executable pinned peer")
    version = subprocess.check_output(["go", "version"], text=True).strip()
    if version != f"go version {manifest['go_version']} linux/amd64":
        raise ValueError(f"build requires native pinned Linux amd64 toolchain, got {version}")
    env = os.environ | manifest["build_environment"]
    overlay, binary = bundle / "overlay.json", bundle / "peer-matrix.test"
    overlay.write_text(json.dumps({"Replace": replace}, indent=2) + "\n")
    command = ["go", "test", f"-overlay={overlay}", "-tags", "picoquic", "-c", "-o", str(binary), "."]
    receipt = {"product_sha": manifest["product_sha"], "manifest_sha256": digest(bundle / "manifest.json"),
               "identity": identity, "peer_binary_sha256": digest(peer), "overlay_sha256": digest(overlay),
               "command": command, "working_directory": str(source), "environment": manifest["build_environment"],
               "go_version": version, "public_enablement": False}
    with (bundle / "build.log").open("x") as log:
        result = subprocess.run(command, cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT)
    receipt["exit_code"] = result.returncode
    if result.returncode == 0:
        receipt["binary_sha256"] = digest(binary)
        receipt["binary_build_info"] = subprocess.check_output(["go", "version", "-m", str(binary)], text=True)
    (bundle / "build-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True, help="fresh extraction of this bundle's source.tar")
    parser.add_argument("--peer-binary", type=Path, default=Path("/usr/local/bin/qgf-r17-peer"))
    args = parser.parse_args()
    raise SystemExit(build(args.bundle.resolve(), args.source.resolve(), args.peer_binary.resolve()))


if __name__ == "__main__":
    main()
