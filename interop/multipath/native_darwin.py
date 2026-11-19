#!/usr/bin/env python3
"""MP-MAC E1 Darwin case runner: a missing, duplicate, skipped or unrecorded case fails.

It builds the root test binary, runs each TestNativeDarwinScalar case alone in its
own process group and validates the case record that process wrote. A passing run
is local smoke evidence for the granted endpoint method, never a support receipt.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import shutil
import subprocess
import time

TEST = "TestNativeDarwinScalar"
SCHEMA = "native-darwin-case/v1"
RESULTS_SCHEMA = "native-darwin-run/v1"
RECORD_ENV = "NATIVE_DARWIN_RECORD"
RECORD_FIELDS = {"schema", "case", "go", "goos", "goarch", "facts"}
# Each family's expected local destination, from packet info on the granted socket.
FAMILIES = {"ipv4": "127.0.0.1", "ipv6": "::1", "dual-stack-mapped-ipv4": "127.0.0.1", "dual-stack-native-ipv6": "::1"}
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
    status = capture("git", "status", "--porcelain", cwd=source)
    return {
        "commit": capture("git", "rev-parse", "HEAD", cwd=source),
        "tree": capture("git", "rev-parse", "HEAD^{tree}", cwd=source),
        "clean": status == "",
    }


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
    cannot have been reused. Its descendants share the group."""
    if process.poll() is None:
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


def validate_results(results):
    """Read-back validation of a results file: a complete passing run, or an error."""
    if results.get("schema") != RESULTS_SCHEMA:
        raise ValueError(f"results schema {results.get('schema')!r} is not {RESULTS_SCHEMA}")
    identity = results.get("identity") or {}
    check_native(identity)
    source, build_identity = results.get("source") or {}, results.get("build") or {}
    if set(source) != {"commit", "tree", "clean"} or not all(isinstance(source[key], str) and source[key] for key in ("commit", "tree")):
        raise ValueError(f"results source identity is incomplete: {source!r}")
    if build_identity.get("go") != identity.get("go") or build_identity.get("mode") != BUILD or not build_identity.get("binary_sha256"):
        raise ValueError(f"results build identity is incomplete or inconsistent: {build_identity!r}")
    instances = results.get("instances") or []
    check_accounting([instance.get("case") for instance in instances])
    for instance in instances:
        if instance.get("failure") is not None or instance.get("exit") != 0:
            raise ValueError(f"{instance.get('case')}: did not pass")
        check_record(instance["case"], identity, instance.get("record") or {})
    if results.get("status") != status():
        raise ValueError(f"results status {results.get('status')!r} is not {status()!r}")


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
    identity = native_identity()
    check_native(identity)
    if shutil.which("go") is None:
        raise SystemExit("missing prerequisite: go")
    args.output.mkdir(parents=True, exist_ok=False)
    binary, build_identity = build(args.source, args.toolchain, args.output)
    identity |= {"go": build_identity["go"], "goos": BUILD["GOOS"], "goarch": BUILD["GOARCH"]}
    results = {"schema": RESULTS_SCHEMA, "source": source_identity(args.source), "build": build_identity, "identity": identity, "instances": []}
    # Stop at the first failure; there is no repeat-until-pass.
    failure = None
    for name in CASES:
        instance, failure = run_case(binary, name, args.output, identity, args.case_timeout)
        instance["failure"] = failure
        results["instances"].append(instance)
        if failure is not None:
            break
    path = args.output / "results.json"
    if failure is None:
        check_accounting([instance["case"] for instance in results["instances"]])
        # Only a complete passing run records a status, so a stopped run claims nothing.
        results["status"] = status()
    path.write_text(json.dumps(results, indent=2) + "\n")
    if failure is not None:
        raise SystemExit(f"stopped: {failure}")
    validate_results(json.loads(path.read_text()))
    print(json.dumps(results["status"]))


if __name__ == "__main__":
    main()
