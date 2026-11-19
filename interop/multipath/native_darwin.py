#!/usr/bin/env python3
"""MP-MAC E1 Darwin case runner: a missing, duplicate, skipped or unrecorded case fails.

It builds the root test binary, runs each TestNativeDarwinScalar case alone in its
own process group and validates the case record that process wrote. A passing run
is local smoke evidence for the granted endpoint method, never a support receipt.
"""

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import signal
import shutil
import subprocess
import tempfile
import time

TEST = "TestNativeDarwinScalar"
SCHEMA = "native-darwin-case/v1"
RESULTS_SCHEMA = "native-darwin-run/v1"
RECORD_ENV = "NATIVE_DARWIN_RECORD"
RECORD_FIELDS = {"schema", "case", "go", "goos", "goarch", "facts"}
# Each family's expected local destination, from packet info on the granted socket.
FAMILIES = {"ipv4": "127.0.0.1", "ipv6": "::1", "dual-stack-mapped-ipv4": "127.0.0.1", "dual-stack-native-ipv6": "::1"}
# The granted socket's wildcard and the form the granted socket reports the peer's source in.
GRANTED_WILDCARD = {"ipv4": "0.0.0.0", "ipv6": "::", "dual-stack-mapped-ipv4": "::", "dual-stack-native-ipv6": "::"}
INBOUND_FORM = {"ipv4": "127.0.0.1", "ipv6": "::1", "dual-stack-mapped-ipv4": "::ffff:127.0.0.1", "dual-stack-native-ipv6": "::1"}
FAMILY_FACTS = {
    "family", "granted_local", "peer", "inbound_source", "inbound_destination", "inbound_interface",
    "inbound_ecn", "outbound_accepted", "outbound_source", "outbound_ecn", "joined",
}
FIXED_FACTS = {
    "grant-refusal": {
        "repeated_grant": "invalid-config", "held_socket": "invalid-config", "connected_socket": "unsupported",
        "send_thread_qos": "unsupported", "regranted_after_join": True,
    },
    "post-join-authority": {
        "endpoint_write_delivered": True, "live_wait": "not-stopping", "joined": True,
        "transport_write_after_join": "closed", "caller_deadline_enforced": True, "caller_write_delivered": True,
    },
}
CASES = (*FAMILIES, *FIXED_FACTS)
NATIVE_FIELDS = ("product_version", "build_version", "kernel", "cpu")
BUILD = {"CGO_ENABLED": "0", "GOOS": "darwin", "GOARCH": "arm64", "GOFLAGS": "-buildvcs=false"}


def command_for(binary, name):
    return [str(binary), f"-test.run=^{TEST}$/^{name}$", "-test.count=1", "-test.timeout=30s", "-test.v"]


def check_output(name, output):
    for word in ("SKIP", "FAIL"):
        if re.search(rf"^\s*(--- )?{word}\b", output, re.MULTILINE):
            raise ValueError(f"{word}: {name}")
    if len(re.findall(rf"^\s*--- PASS: {TEST}/{re.escape(name)} ", output, re.MULTILINE)) != 1:
        raise ValueError(f"{name} must pass exactly once")


def parse_record(text):
    try:
        record = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"malformed case record: {error}") from None
    if not isinstance(record, dict):
        raise ValueError("malformed case record: not an object")
    return record


def check_family_facts(name, facts):
    expected = {"family": name, "inbound_destination": FAMILIES[name], "inbound_ecn": "CE", "outbound_accepted": 1, "outbound_ecn": "ECT(0)", "joined": True}
    for key, value in expected.items():
        if facts[key] != value or isinstance(facts[key], bool) != isinstance(value, bool):
            raise ValueError(f"{name}: fact {key} is {facts[key]!r}, expected {value!r}")
    interface = facts["inbound_interface"]
    if isinstance(interface, bool) or not isinstance(interface, int) or interface <= 0:
        raise ValueError(f"{name}: fact inbound_interface is {interface!r}, expected a positive index")
    granted, peer = parse_tuple(name, "granted_local", facts), parse_tuple(name, "peer", facts)
    expected = {
        "granted_local": (ipaddress.ip_address(GRANTED_WILDCARD[name]), granted[1]),
        "peer": (ipaddress.ip_address(FAMILIES[name]), peer[1]),
        "inbound_source": (ipaddress.ip_address(INBOUND_FORM[name]), peer[1]),
        "outbound_source": (ipaddress.ip_address(FAMILIES[name]), granted[1]),
    }
    for key, value in expected.items():
        if parse_tuple(name, key, facts) != value:
            raise ValueError(f"{name}: fact {key} is {facts[key]!r}, expected {value[0]} port {value[1]}")


def parse_tuple(name, key, facts):
    """Parses a Go UDP address string; the standard ipaddress module owns the address syntax."""
    text = facts[key]
    host, _, port = text.rpartition(":") if isinstance(text, str) else ("", "", "")
    try:
        address = ipaddress.ip_address(host[1:-1] if host.startswith("[") and host.endswith("]") else host)
        number = int(port)
    except ValueError:
        raise ValueError(f"{name}: fact {key} is not a UDP address: {text!r}") from None
    if not 0 < number < 65536 or not port.isdigit():
        raise ValueError(f"{name}: fact {key} has no valid port: {text!r}")
    return address, number


def check_record(name, identity, record):
    if set(record) != RECORD_FIELDS:
        raise ValueError(f"{name}: record fields {sorted(record)} are not {sorted(RECORD_FIELDS)}")
    expected = {"schema": SCHEMA, "case": name, "go": identity["go"], "goos": identity["goos"], "goarch": identity["goarch"]}
    for field, value in expected.items():
        if record[field] != value:
            raise ValueError(f"{name}: record {field} {record[field]!r} is not {value!r}")
    facts = record["facts"]
    declared = FAMILY_FACTS if name in FAMILIES else set(FIXED_FACTS[name])
    if not isinstance(facts, dict) or set(facts) != declared:
        raise ValueError(f"{name}: facts {sorted(facts) if isinstance(facts, dict) else facts!r} are not {sorted(declared)}")
    if name in FAMILIES:
        check_family_facts(name, facts)
        return
    for key, value in FIXED_FACTS[name].items():
        if facts[key] != value or type(facts[key]) is not type(value):
            raise ValueError(f"{name}: fact {key} is {facts[key]!r}, expected {value!r}")


def check_accounting(names):
    unknown = sorted(set(names) - set(CASES))
    missing = [name for name in CASES if name not in names]
    duplicate = sorted({name for name in names if names.count(name) > 1})
    if unknown or missing or duplicate:
        raise ValueError(f"expected each of the {len(CASES)} cases exactly once: missing {missing}, duplicate {duplicate}, unknown {unknown}")


def check_native(identity):
    if identity.get("system") != "Darwin" or identity.get("machine") != "arm64" or identity.get("proc_translated") != "0":
        raise ValueError(f"requires native Darwin arm64, got {identity.get('system')}/{identity.get('machine')} translated={identity.get('proc_translated')}")


def capture(*command, env=None, cwd=None):
    return subprocess.run(command, env=env, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def native_identity():
    # A translated (Rosetta) process reports 1; an arm64 binary cannot be translated.
    translated = subprocess.run(["sysctl", "-n", "sysctl.proc_translated"], capture_output=True, text=True).stdout.strip() or "0"
    return {
        "system": platform.system(),
        "machine": platform.machine(),
        "proc_translated": translated,
        "product_version": capture("sw_vers", "-productVersion"),
        "build_version": capture("sw_vers", "-buildVersion"),
        "kernel": capture("uname", "-a"),
        "cpu": capture("sysctl", "-n", "machdep.cpu.brand_string"),
    }


def source_identity(source):
    """The tree is the working tree that was built, tracked and untracked files not
    ignored, written through a private index; clean means it equals HEAD's tree."""
    head_tree = capture("git", "rev-parse", "HEAD^{tree}", cwd=source)
    with tempfile.TemporaryDirectory() as directory:
        env = os.environ | {"GIT_INDEX_FILE": str(Path(directory) / "index")}
        capture("git", "read-tree", "HEAD", env=env, cwd=source)
        capture("git", "add", "--all", env=env, cwd=source)
        tree = capture("git", "write-tree", env=env, cwd=source)
    return {"commit": capture("git", "rev-parse", "HEAD", cwd=source), "tree": tree, "head_tree": head_tree, "clean": tree == head_tree}


def build(source, toolchain, output):
    env = os.environ | BUILD | {"GOTOOLCHAIN": toolchain}
    reported = capture("go", "env", "GOVERSION", env=env, cwd=source)
    if toolchain != "local" and reported != toolchain:
        raise ValueError(f"requested {toolchain}, got {reported}")
    binary = output / "native-darwin.test"
    capture("go", "test", "-c", "-o", str(binary.resolve()), ".", env=env, cwd=source)
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    return binary, {"go": reported, "toolchain": toolchain, "mode": dict(BUILD), "binary_sha256": digest}


def stop_group(process):
    """Kill the case's process group while its leader is unreaped, so the group ID
    cannot have been reused. Its descendants share the group. It never polls: that
    could reap a leader that exited while a descendant still holds the pipe."""
    if process.returncode is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_case(binary, name, output, identity, timeout):
    directory = output / name
    directory.mkdir(parents=True)
    record_path = directory / "record.json"
    command = command_for(Path(binary).resolve(), name)
    instance = {"case": name, "command": command, "exit": None, "seconds": None, "record": None}
    started = time.monotonic()
    process = subprocess.Popen(command, env=os.environ | {RECORD_ENV: str(record_path)}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    timed_out = False
    try:
        text, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        stop_group(process)
        # The group is dead, so the pipe reaches EOF; this also reaps the leader.
        text, _ = process.communicate()
    finally:
        stop_group(process)
        process.wait()
    instance["seconds"] = round(time.monotonic() - started, 3)
    (directory / "test.log").write_text(text or "")
    if timed_out:
        return instance, f"timeout after {timeout} s: the case process group was killed and reaped"
    instance["exit"] = process.returncode
    if process.returncode != 0:
        return instance, f"exit {process.returncode}"
    try:
        check_output(name, text)
        if not record_path.exists():
            raise ValueError(f"{name}: no case record was written")
        instance["record"] = parse_record(record_path.read_text())
        check_record(name, identity, instance["record"])
    except (ValueError, OSError) as error:
        return instance, str(error)
    return instance, None


def status():
    return {"cases": len(CASES), "status": "pass", "support_receipt": False}


def is_text(value):
    return isinstance(value, str) and value != ""


def is_hex(length):
    return lambda value: isinstance(value, str) and re.fullmatch(f"[0-9a-f]{{{length}}}", value) is not None


def is_integer(value):
    return type(value) is int


# The declared results shape: every section has exactly these fields, each with its
# type. Cross-field consistency follows in validate_results; nothing else is read.
RESULTS_SHAPE = {
    "source": {"commit": is_hex(40), "tree": is_hex(40), "head_tree": is_hex(40), "clean": lambda value: type(value) is bool},
    "build": {"go": is_text, "toolchain": is_text, "mode": lambda value: value == BUILD, "binary_sha256": is_hex(64)},
    "identity": {key: is_text for key in ("system", "machine", "proc_translated", *NATIVE_FIELDS, "go", "goos", "goarch")},
    "instance": {
        "case": is_text, "command": lambda value: isinstance(value, list) and all(map(is_text, value)),
        "exit": lambda value: is_integer(value) and value == 0, "seconds": lambda value: type(value) in (int, float) and value >= 0,
        "record": lambda value: isinstance(value, dict), "failure": lambda value: value is None,
    },
}
RESULTS_FIELDS = {"schema", "source", "build", "identity", "instances", "status"}


def check_shape(section, value, shape):
    if not isinstance(value, dict) or set(value) != set(shape):
        raise ValueError(f"results {section} fields {sorted(value) if isinstance(value, dict) else value!r} are not {sorted(shape)}")
    invalid = sorted(key for key, valid in shape.items() if not valid(value[key]))
    if invalid:
        raise ValueError(f"results {section} has invalid {invalid}")


def validate_results(results):
    """Read-back validation of a results file: a complete passing run, or an error."""
    if not isinstance(results, dict) or set(results) != RESULTS_FIELDS:
        raise ValueError(f"results fields {sorted(results) if isinstance(results, dict) else results!r} are not {sorted(RESULTS_FIELDS)}")
    if results["schema"] != RESULTS_SCHEMA:
        raise ValueError(f"results schema {results['schema']!r} is not {RESULTS_SCHEMA}")
    source, build_identity, identity = results["source"], results["build"], results["identity"]
    check_shape("source", source, RESULTS_SHAPE["source"])
    check_shape("build", build_identity, RESULTS_SHAPE["build"])
    check_shape("identity", identity, RESULTS_SHAPE["identity"])
    if source["clean"] != (source["tree"] == source["head_tree"]):
        raise ValueError(f"results source clean flag contradicts its trees: {source!r}")
    if build_identity["toolchain"] not in ("local", build_identity["go"]):
        raise ValueError(f"results build toolchain {build_identity['toolchain']!r} is not local or the built {build_identity['go']!r}")
    expected = {"go": build_identity["go"], "goos": BUILD["GOOS"], "goarch": BUILD["GOARCH"]}
    if {key: identity[key] for key in expected} != expected:
        raise ValueError(f"results run identity contradicts the build: {expected!r}")
    check_native(identity)
    instances = results["instances"]
    if not isinstance(instances, list):
        raise ValueError("results instances are not a list")
    for instance in instances:
        check_shape("instance", instance, RESULTS_SHAPE["instance"])
    check_accounting([instance["case"] for instance in instances])
    for instance in instances:
        check_record(instance["case"], identity, instance["record"])
    if results["status"] != status():
        raise ValueError(f"results status {results['status']!r} is not {status()!r}")


def run(source, output, toolchain, case_timeout):
    """Runs every case once and returns the results; stops at the first failure."""
    identity = native_identity()
    check_native(identity)
    if shutil.which("go") is None:
        raise SystemExit("missing prerequisite: go")
    # Snapshot the source before creating output, which may lie inside the tree.
    source_snapshot = source_identity(source)
    output.mkdir(parents=True, exist_ok=False)
    binary, build_identity = build(source, toolchain, output)
    identity |= {"go": build_identity["go"], "goos": BUILD["GOOS"], "goarch": BUILD["GOARCH"]}
    results = {"schema": RESULTS_SCHEMA, "source": source_snapshot, "build": build_identity, "identity": identity, "instances": []}
    # There is no repeat-until-pass.
    failure = None
    for name in CASES:
        instance, failure = run_case(binary, name, output, identity, case_timeout)
        instance["failure"] = failure
        results["instances"].append(instance)
        if failure is not None:
            break
    if failure is None:
        check_accounting([instance["case"] for instance in results["instances"]])
        # Only a complete passing run records a status, so a stopped run claims nothing.
        results["status"] = status()
    (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    return results, failure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="a new directory for this run")
    parser.add_argument("--toolchain", default="local", help="GOTOOLCHAIN for the build, such as go1.27.4")
    parser.add_argument("--source", type=Path, default=Path("."), help="the module root to build")
    parser.add_argument("--case-timeout", type=float, default=60.0)
    parser.add_argument("--validate", type=Path, help="validate an existing results.json and exit")
    args = parser.parse_args()
    if args.validate:
        validate_results(json.loads(args.validate.read_text()))
        print("valid")
        return
    if args.output is None:
        parser.error("--output is required")
    results, failure = run(args.source, args.output, args.toolchain, args.case_timeout)
    if failure is not None:
        raise SystemExit(f"stopped: {failure}")
    validate_results(json.loads((args.output / "results.json").read_text()))
    print(json.dumps(results["status"]))


if __name__ == "__main__":
    main()
