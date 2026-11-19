#!/usr/bin/env python3
"""MP-MAC Darwin case runner: a missing, duplicate, skipped or unrecorded case fails.

It builds the root test binary, runs each case of the selected profile alone in its
own process group and validates the case record that process wrote. The scalar
profile runs TestNativeDarwinScalar (E1, with E3's scalar contention record); the
pressure profile builds with the native_pressure tag and runs E3's bounded
socket-pressure observation. A passing run is local evidence for the endpoint
method, never a support receipt.
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
# v2 added the profile and E3's scalar-contention case.
RESULTS_SCHEMA = "native-darwin-run/v2"
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
# E3's contention records. The scalar development case must be a complete, fault-free
# observation with progress on every lane; the pressure observation records what it saw.
CONTENTION_CASES = {"scalar-contention": True, "socket-pressure": False}
CASES = (*FAMILIES, *FIXED_FACTS, "scalar-contention")
NATIVE_FIELDS = ("product_version", "build_version", "kernel", "cpu")
BUILD = {"CGO_ENABLED": "0", "GOOS": "darwin", "GOARCH": "arm64", "GOFLAGS": "-buildvcs=false"}
# Each profile's test, its cases in order and its build mode. Only the pressure
# profile's tag builds its operational mode into the binary.
PROFILES = {
    "scalar": {"test": TEST, "cases": CASES, "mode": BUILD},
    "pressure": {"test": "TestNativeDarwinPressure", "cases": ("socket-pressure",), "mode": BUILD | {"GOFLAGS": "-buildvcs=false -tags=native_pressure"}},
}


def command_for(binary, name, test=TEST):
    return [str(binary), f"-test.run=^{test}$/^{name}$", "-test.count=1", "-test.timeout=30s", "-test.v"]


def check_output(name, output, test=TEST):
    for word in ("SKIP", "FAIL"):
        if re.search(rf"^\s*(--- )?{word}\b", output, re.MULTILINE):
            raise ValueError(f"{word}: {name}")
    if len(re.findall(rf"^\s*--- PASS: {test}/{re.escape(name)} ", output, re.MULTILINE)) != 1:
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


CONTENTION_FACTS = {"status", "pressure_wait", "fault", "unfinished_participants", "diagnostics_dropped", "load", "writer", "lanes", "participant_occupancy_max"}
LOAD_FIELDS = ("participants", "requests", "members", "payload", "budget_ms", "window_ms")
ERROR_CLASSES = ("enobufs", "eagain", "emsgsize", "deadline", "other")
WRITER_FIELDS = ("writes", "max_write_ns", "long_writes", "deadline_waits")
LANES = ("path0", "path1", "control")
LANE_COUNTS = (
    "offers", "admitted", "refused", "closed", "results", "withdrawn",
    "accepted", "uncertain", "unsubmitted", "failed", "diagnostics", "occupancy_max", "native_return_to_take_max_ns",
)
FAULTS = {"none", "overdue", "late-return", "native"}


def check_counts(name, section, value, fields, extra=()):
    """A section with exactly fields as non-negative integers, plus the extra keys."""
    if not isinstance(value, dict) or set(value) != {*fields, *extra}:
        raise ValueError(f"{name}: {section} fields {sorted(value) if isinstance(value, dict) else value!r} are not {sorted({*fields, *extra})}")
    invalid = sorted(key for key in fields if type(value[key]) is not int or value[key] < 0)
    if invalid:
        raise ValueError(f"{name}: {section} has invalid {invalid}")


def contention_status(facts):
    """The status and pressure-wait result the recorded facts imply. Only a load that
    every producer finished inside its window, on an endpoint that never faulted,
    fully taken and fully observed, is complete; only a complete observation can
    report that no pressure wait occurred."""
    lanes, requests = facts["lanes"], facts["load"]["requests"]
    if facts["unfinished_participants"] != 0 or facts["fault"] != "none" or any(lane["admitted"] != requests or lane["withdrawn"] != 0 for lane in lanes):
        status = "interrupted"
    elif facts["diagnostics_dropped"] != 0 or any(lane["diagnostics"] != lane["results"] for lane in lanes):
        status = "incomplete-coverage"
    else:
        status = "complete"
    if facts["writer"]["deadline_waits"] > 0:
        return status, "observed"
    return status, "not-observed" if status == "complete" else "unknown"


def check_contention_facts(name, facts):
    load, writer, lanes, occupancy = facts["load"], facts["writer"], facts["lanes"], facts["participant_occupancy_max"]
    check_counts(name, "load", load, LOAD_FIELDS)
    if min(load["participants"], load["requests"], load["members"], load["payload"]) == 0:
        raise ValueError(f"{name}: load {load!r} offers nothing")
    check_counts(name, "writer", writer, WRITER_FIELDS, ("errors",))
    check_counts(name, "writer errors", writer["errors"], ERROR_CLASSES)
    for key in ("diagnostics_dropped", "unfinished_participants"):
        if type(facts[key]) is not int or facts[key] < 0:
            raise ValueError(f"{name}: fact {key} is {facts[key]!r}")
    if facts["unfinished_participants"] > load["participants"]:
        raise ValueError(f"{name}: more unfinished participants than participants")
    if facts["fault"] not in FAULTS:
        raise ValueError(f"{name}: fact fault is {facts['fault']!r}, not one of {sorted(FAULTS)}")
    participants = load["participants"]
    if not isinstance(lanes, list) or len(lanes) != participants * len(LANES):
        raise ValueError(f"{name}: expected {participants * len(LANES)} lanes")
    for index, lane in enumerate(lanes):
        check_counts(name, f"lane {index}", lane, LANE_COUNTS, ("participant", "lane"))
        where = f"{name}: lane {index}"
        if (lane["participant"], lane["lane"]) != (index // len(LANES), LANES[index % len(LANES)]) or type(lane["participant"]) is not int:
            raise ValueError(f"{where} is {lane['participant']!r}/{lane['lane']!r}, expected {index // len(LANES)}/{LANES[index % len(LANES)]}")
        if lane["offers"] != lane["admitted"] + lane["refused"] + lane["closed"]:
            raise ValueError(f"{where}: offers are not admitted + refused + closed")
        if lane["admitted"] != lane["results"] + lane["withdrawn"] or lane["admitted"] > load["requests"]:
            raise ValueError(f"{where}: admitted is not results + withdrawn within the offered requests")
        if lane["accepted"] + lane["uncertain"] + lane["unsubmitted"] != lane["results"] * load["members"] or lane["failed"] > lane["results"]:
            raise ValueError(f"{where}: datagram outcomes do not add up to its results")
        if lane["occupancy_max"] > lane["admitted"] or (lane["admitted"] > 0) != (lane["occupancy_max"] > 0):
            raise ValueError(f"{where}: occupancy_max does not fit its admissions")
    if not isinstance(occupancy, list) or len(occupancy) != participants or any(type(value) is not int or value < 0 for value in occupancy):
        raise ValueError(f"{name}: participant_occupancy_max is not one count per participant")
    if writer["writes"] < sum(lane["accepted"] + lane["uncertain"] for lane in lanes):
        raise ValueError(f"{name}: fewer native writes than accepted or uncertain datagrams")
    if sum(writer["errors"].values()) > writer["writes"] or writer["long_writes"] > writer["writes"] or writer["deadline_waits"] > writer["errors"]["deadline"]:
        raise ValueError(f"{name}: writer observations contradict each other: {writer!r}")
    # A pressure wait is a native timeout, which the endpoint reports as an uncertain
    # member of a failed result; only a withdrawn result can hide it.
    if writer["deadline_waits"] > 0 and not any(lane["withdrawn"] for lane in lanes) and not any(lane["uncertain"] and lane["failed"] for lane in lanes):
        raise ValueError(f"{name}: an observed pressure wait has no uncertain member in a failed result")
    status, pressure = contention_status(facts)
    if (facts["status"], facts["pressure_wait"]) != (status, pressure):
        raise ValueError(f"{name}: status {facts['status']!r} and pressure_wait {facts['pressure_wait']!r}, the counts imply {status!r} and {pressure!r}")
    if CONTENTION_CASES[name] and (status != "complete" or facts["fault"] != "none" or any(lane["accepted"] == 0 for lane in lanes)):
        raise ValueError(f"{name}: the development case needs a complete, fault-free observation with progress on every lane")


def check_record(name, identity, record):
    if set(record) != RECORD_FIELDS:
        raise ValueError(f"{name}: record fields {sorted(record)} are not {sorted(RECORD_FIELDS)}")
    expected = {"schema": SCHEMA, "case": name, "go": identity["go"], "goos": identity["goos"], "goarch": identity["goarch"]}
    for field, value in expected.items():
        if record[field] != value:
            raise ValueError(f"{name}: record {field} {record[field]!r} is not {value!r}")
    facts = record["facts"]
    declared = FAMILY_FACTS if name in FAMILIES else CONTENTION_FACTS if name in CONTENTION_CASES else set(FIXED_FACTS[name])
    if not isinstance(facts, dict) or set(facts) != declared:
        raise ValueError(f"{name}: facts {sorted(facts) if isinstance(facts, dict) else facts!r} are not {sorted(declared)}")
    if name in FAMILIES:
        check_family_facts(name, facts)
        return
    if name in CONTENTION_CASES:
        check_contention_facts(name, facts)
        return
    for key, value in FIXED_FACTS[name].items():
        if facts[key] != value or type(facts[key]) is not type(value):
            raise ValueError(f"{name}: fact {key} is {facts[key]!r}, expected {value!r}")


def check_accounting(names, cases=CASES):
    unknown = sorted(set(names) - set(cases))
    missing = [name for name in cases if name not in names]
    duplicate = sorted({name for name in names if names.count(name) > 1})
    if unknown or missing or duplicate:
        raise ValueError(f"expected each of the {len(cases)} cases exactly once: missing {missing}, duplicate {duplicate}, unknown {unknown}")


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


# The file lists `go help list` declares as package build inputs. Only the package
# under test contributes its test lists to the test binary.
GO_LIST_FILE_FIELDS = ("GoFiles", "CgoFiles", "CFiles", "CXXFiles", "MFiles", "HFiles", "FFiles", "SFiles", "SwigFiles", "SwigCXXFiles", "SysoFiles", "EmbedFiles")
GO_LIST_TEST_FIELDS = ("TestGoFiles", "XTestGoFiles", "TestEmbedFiles", "XTestEmbedFiles")


def build_env(toolchain, profile="scalar"):
    return os.environ | PROFILES[profile]["mode"] | {"GOTOOLCHAIN": toolchain}


def parse_go_list(text, directory):
    """The main module's files that the test build of the package in directory reads,
    from a `go list -deps -test -json` stream the json module parses. Generated files
    outside the module, such as the test main, and other modules' packages, which
    go.sum and the toolchain identify, are not source."""
    decoder, index, files, tested = json.JSONDecoder(), 0, set(), Path(directory).resolve()
    while True:
        while index < len(text) and text[index].isspace():
            index += 1
        if index == len(text):
            return files
        package, index = decoder.raw_decode(text, index)
        module = package.get("Module") or {}
        if package.get("Standard") or not module.get("Main"):
            continue
        root, package_directory = Path(module["GoMod"]).resolve().parent, Path(package["Dir"]).resolve()
        fields = GO_LIST_FILE_FIELDS + (GO_LIST_TEST_FIELDS if package_directory == tested else ())
        for field in fields:
            files.update(path for path in (package_directory / name for name in package.get(field) or ()) if path.is_relative_to(root))
        files.update(path for path in (root / "go.mod", root / "go.sum") if path.exists())


def selected_sources(source, toolchain, profile="scalar"):
    """The main-module files the profile's test build of the source directory reads."""
    return parse_go_list(capture("go", "list", "-deps", "-test", "-json", ".", env=build_env(toolchain, profile), cwd=source), source)


def tree_paths(source, tree):
    top = Path(capture("git", "rev-parse", "--show-toplevel", cwd=source))
    listed = subprocess.run(["git", "ls-tree", "-r", "-z", "--name-only", tree], cwd=top, check=True, capture_output=True).stdout
    return {(top / name).resolve() for name in os.fsdecode(listed).split("\0") if name}


def check_build_sources(selected, recorded):
    """Every file the build reads from the main module must be in the recorded tree."""
    missing = sorted(str(path) for path in {path.resolve() for path in selected} - recorded)
    if missing:
        raise ValueError(f"the build reads source that the recorded tree omits: {missing}")


def build(source, toolchain, output, profile="scalar"):
    env = build_env(toolchain, profile)
    reported = capture("go", "env", "GOVERSION", env=env, cwd=source)
    if toolchain != "local" and reported != toolchain:
        raise ValueError(f"requested {toolchain}, got {reported}")
    binary = output / "native-darwin.test"
    capture("go", "test", "-c", "-o", str(binary.resolve()), ".", env=env, cwd=source)
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    return binary, {"go": reported, "toolchain": toolchain, "mode": dict(PROFILES[profile]["mode"]), "binary_sha256": digest}


def stop_group(process):
    """Kill the case's process group while its leader is unreaped, so the group ID
    cannot have been reused. Its descendants share the group. It never polls: that
    could reap a leader that exited while a descendant still holds the pipe."""
    if process.returncode is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_case(binary, name, output, identity, timeout, test=TEST):
    directory = output / name
    directory.mkdir(parents=True)
    record_path = directory / "record.json"
    command = command_for(Path(binary).resolve(), name, test)
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
        check_output(name, text, test)
        if not record_path.exists():
            raise ValueError(f"{name}: no case record was written")
        instance["record"] = parse_record(record_path.read_text())
        check_record(name, identity, instance["record"])
    except (ValueError, OSError) as error:
        return instance, str(error)
    return instance, None


def status(profile="scalar"):
    return {"cases": len(PROFILES[profile]["cases"]), "status": "pass", "support_receipt": False}


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
    "build": {"go": is_text, "toolchain": is_text, "mode": lambda value: value in [profile["mode"] for profile in PROFILES.values()], "binary_sha256": is_hex(64)},
    "identity": {key: is_text for key in ("system", "machine", "proc_translated", *NATIVE_FIELDS, "go", "goos", "goarch")},
    "status": {
        "cases": is_integer, "status": lambda value: value == "pass", "support_receipt": lambda value: value is False,
    },
    "instance": {
        "case": is_text, "command": lambda value: isinstance(value, list) and all(map(is_text, value)),
        "exit": lambda value: is_integer(value) and value == 0, "seconds": lambda value: type(value) in (int, float) and value >= 0,
        "record": lambda value: isinstance(value, dict), "failure": lambda value: value is None,
    },
}
RESULTS_FIELDS = {"schema", "profile", "source", "build", "identity", "instances", "status"}


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
    if results["profile"] not in PROFILES:
        raise ValueError(f"results profile {results['profile']!r} is not one of {sorted(PROFILES)}")
    profile = PROFILES[results["profile"]]
    source, build_identity, identity = results["source"], results["build"], results["identity"]
    check_shape("source", source, RESULTS_SHAPE["source"])
    check_shape("build", build_identity, RESULTS_SHAPE["build"])
    check_shape("identity", identity, RESULTS_SHAPE["identity"])
    if source["clean"] != (source["tree"] == source["head_tree"]):
        raise ValueError(f"results source clean flag contradicts its trees: {source!r}")
    if build_identity["mode"] != profile["mode"]:
        raise ValueError(f"results build mode {build_identity['mode']!r} is not the {results['profile']} profile's")
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
    check_accounting([instance["case"] for instance in instances], profile["cases"])
    for instance in instances:
        check_record(instance["case"], identity, instance["record"])
    check_shape("status", results["status"], RESULTS_SHAPE["status"])
    if results["status"]["cases"] != len(profile["cases"]):
        raise ValueError(f"results status counts {results['status']['cases']} cases, not {len(profile['cases'])}")


def run(source, output, toolchain, case_timeout, profile="scalar"):
    """Runs every case of the profile once and returns the results; stops at the
    first failure."""
    identity = native_identity()
    check_native(identity)
    if shutil.which("go") is None:
        raise SystemExit("missing prerequisite: go")
    # Snapshot the source before creating output, which may lie inside the tree, and
    # refuse a build that would read source the snapshot leaves out.
    source_snapshot = source_identity(source)
    check_build_sources(selected_sources(source, toolchain, profile), tree_paths(source, source_snapshot["tree"]))
    output.mkdir(parents=True, exist_ok=False)
    binary, build_identity = build(source, toolchain, output, profile)
    identity |= {"go": build_identity["go"], "goos": BUILD["GOOS"], "goarch": BUILD["GOARCH"]}
    results = {"schema": RESULTS_SCHEMA, "profile": profile, "source": source_snapshot, "build": build_identity, "identity": identity, "instances": []}
    # There is no repeat-until-pass, and a negative pressure observation is a result.
    failure = None
    for name in PROFILES[profile]["cases"]:
        instance, failure = run_case(binary, name, output, identity, case_timeout, PROFILES[profile]["test"])
        instance["failure"] = failure
        results["instances"].append(instance)
        if failure is not None:
            break
    if failure is None:
        check_accounting([instance["case"] for instance in results["instances"]], PROFILES[profile]["cases"])
        # Only a complete passing run records a status, so a stopped run claims nothing.
        results["status"] = status(profile)
    (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    return results, failure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="a new directory for this run")
    parser.add_argument("--toolchain", default="local", help="GOTOOLCHAIN for the build, such as go1.27.4")
    parser.add_argument("--source", type=Path, default=Path("."), help="the module root to build")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="scalar", help="scalar: E1's cases and E3's contention record; pressure: E3's socket-pressure observation")
    parser.add_argument("--case-timeout", type=float, default=60.0)
    parser.add_argument("--validate", type=Path, help="validate an existing results.json and exit")
    args = parser.parse_args()
    if args.validate:
        validate_results(json.loads(args.validate.read_text()))
        print("valid")
        return
    if args.output is None:
        parser.error("--output is required")
    results, failure = run(args.source, args.output, args.toolchain, args.case_timeout, args.profile)
    if failure is not None:
        raise SystemExit(f"stopped: {failure}")
    validate_results(json.loads((args.output / "results.json").read_text()))
    print(json.dumps(results["status"]))


if __name__ == "__main__":
    main()
