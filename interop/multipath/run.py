#!/usr/bin/env python3
"""Required peer scenarios: a missing or skipped role is a failed claim."""

import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import time

import candidate_binding

PACKAGE = "github.com/GridCastIO/quicquic-go/integrationtests/self"
EXPECTED = ["TestPicoquicOrdinaryControl/client", "TestPicoquicOrdinaryControl/server"]
# R14's two-path smoke reads private owners, so it runs in the root package.
SMOKE_PACKAGE = "github.com/GridCastIO/quicquic-go"
SMOKE_EXPECTED = ["TestPicoquicMultipathSmoke/client", "TestPicoquicMultipathSmoke/server"]
MATRIX_SCENARIOS = (
    "useful-transfer", "absent-negotiation", "path-zero-ack",
    "key-update-silent-path", "status-backup-failover",
    "abandon-reopen-late-feedback", "same-id-migration-rebinding",
    "unequal-mtu-invalid-frame",
)
MATRIX_EXPECTED = [f"TestPicoquicMultipathMatrix/{scenario}/{role}"
                   for scenario in MATRIX_SCENARIOS for role in ("client", "server")]
ZERO_EXPECTED = ["TestMultipathNegotiatedZeroVectors", "TestMultipathNegotiatedZeroControlledPeer"]
# The native profile compiles and lists the matrix; it executes no multipath case before Q2.
DISCOVERY_EXPECTED = ["TestPicoquicMultipathMatrix"]
PICOQUIC_PIN = "fbd46d9a1f54ebf9397f2ee6355b5019ab379fb7"
PICOTLS_PIN = "e446233b4100ebcdec60901c05bfb7f4cd369c5d"
# Each profile is an explicit execution identity. The Linux Docker profile is the
# default and keeps its image, toolchain and line-buffered launch assumptions.
PROFILES = {"linux-docker": ("linux", ("x86_64", "amd64")), "darwin-native": ("darwin", ("arm64",))}
NATIVE_PROFILE = "darwin-native"
PEER_BINARIES = ("picoquicdemo", "qgf-r17-peer")
# The candidate checkout a native test binary is bound to (#1528): by default the one that
# holds this runner, which is the protocol's $SRC.
SOURCE = Path(__file__).resolve().parents[2]


BBR_SCENARIOS = ("useful-transfer", "abandon-reopen-late-feedback", "same-id-migration-rebinding")


def matrix_expected(controller):
    if controller not in ("reno", "bbrv3"):
        raise ValueError("unsupported matrix controller")
    scenarios = BBR_SCENARIOS if controller == "bbrv3" else MATRIX_SCENARIOS
    return [f"TestPicoquicMultipathMatrix/{scenario}/{role}"
            for scenario in scenarios for role in ("client", "server")]


def matrix_invocation(scenario, role, test_binary=None, controller="reno"):
    if f"TestPicoquicMultipathMatrix/{scenario}/{role}" not in matrix_expected(controller):
        raise ValueError("the matrix requires one fixed scenario and endpoint role")
    expression = f"^TestPicoquicMultipathMatrix$/^{scenario}$/^{role}$"
    command = ["go", "test", "-json", "-tags=picoquic", f"-run={expression}", "-count=1", "-timeout=90s", "."]
    if test_binary:
        command = ["go", "tool", "test2json", "-t", "-p", SMOKE_PACKAGE, str(test_binary),
                   "-test.v=test2json", f"-test.run={expression}", "-test.count=1", "-test.timeout=90s"]
    return command, [f"TestPicoquicMultipathMatrix/{scenario}/{role}"]


def check_matrix(root, controller="reno", policy="primary-backup"):
    expected = matrix_expected(controller)
    identity = None
    expected_paths = set()
    # Require every log before comparing metadata, so missing evidence wins.
    for case in expected:
        _, scenario, role = case.split("/")
        expected_paths.add(root / scenario / role / "go-test.jsonl")
    actual_paths = set(root.glob("*/*/go-test.jsonl"))
    if actual_paths != expected_paths:
        raise ValueError(f"missing or unexpected matrix case logs: {actual_paths ^ expected_paths}")
    for case in expected:
        _, scenario, role = case.split("/")
        directory = root / scenario / role
        check_cases((directory / "go-test.jsonl").read_text().splitlines(), SMOKE_PACKAGE, [case])
        result = json.loads((directory / "result.json").read_text())
        if result.get("status") != "pass" or result.get("executed") != [case] or not result.get("identity"):
            raise ValueError(f"invalid case receipt: {case}")
        if result.get("controller", "reno") != controller:
            raise ValueError(f"matrix controller mismatch: {case}")
        if result.get("policy", "primary-backup") != policy:
            raise ValueError(f"matrix policy mismatch: {case}")
        if identity is None:
            identity = result["identity"]
        elif result["identity"] != identity:
            raise ValueError(f"matrix candidate/build/kernel identity changed: {case}")
    result = {"status": "pass", "executed": expected, "identity": identity, "controller": controller, "policy": policy,
              "guarantee": "example-level; fixed draft-21 QUIC v1 scenarios only"}
    if controller == "reno":
        zero = root / "negotiated-zero"
        if not (zero / "go-test.jsonl").is_file() or not (zero / "result.json").is_file():
            raise ValueError("missing negotiated-zero normative/controlled evidence")
        check_cases((zero / "go-test.jsonl").read_text().splitlines(), SMOKE_PACKAGE, ZERO_EXPECTED)
        zero_result = json.loads((zero / "result.json").read_text())
        if zero_result.get("status") != "pass" or zero_result.get("executed") != ZERO_EXPECTED or zero_result.get("identity") != identity:
            raise ValueError("negotiated-zero receipt identity/accounting mismatch")
        result["negotiated_zero"] = {"executed": ZERO_EXPECTED, "independent_peer": False}
    return result


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def is_hex(value, length):
    return isinstance(value, str) and len(value) == length and all(c in "0123456789abcdef" for c in value)


def hex_text(length):
    return lambda value: is_hex(value, length)


def text(value):
    return isinstance(value, str) and value != ""


def exactly(expected):
    return lambda value: value == expected and type(value) is type(expected)


def nonnegative_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def command_line(value):
    return isinstance(value, list) and value != [] and all(text(item) for item in value)


def check_record(value, schema, where):
    """Check one parsed JSON value against a typed schema: nested dicts are exact objects,
    callables check values. Unknown, missing or malformed fields fail at any depth."""
    if not isinstance(value, dict) or set(value) != set(schema):
        raise ValueError(f"malformed {where} fields")
    for key, check in schema.items():
        if isinstance(check, dict):
            check_record(value[key], check, f"{where}.{key}")
        elif not check(value[key]):
            raise ValueError(f"malformed {where}.{key}: {value[key]!r}")
    return value


def read_record(path, schema, where):
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"unreadable {where}: {error}") from error
    return check_record(value, schema, where)


SHA256 = hex_text(64)
REPEATED_SUBTEST = re.compile(r"(.+)#\d+")
GO_RELEASE = re.compile(r"go version go\d+\.\d+(?:\.\d+)?(?:(?:rc|beta)\d+)?(?: X:\S+)? darwin/arm64")
BUILD_IDENTITY_SCHEMA = {
    "version": exactly(1), "profile": exactly(NATIVE_PROFILE),
    "platform": {"system": text, "machine": text, "release": text, "macos": text},
    "picoquic": exactly(PICOQUIC_PIN), "picotls": exactly(PICOTLS_PIN),
    "toolchain": {"cc": text, "sdk_version": text, "sdk_path": text, "cmake": text, "cmake_sha256": SHA256,
                  "pkg_config": text, "pkg_config_sha256": SHA256, "openssl": text, "openssl_root": text,
                  "openssl_static_sha256": {"libcrypto.a": SHA256, "libssl.a": SHA256}},
    "peer_driver_sha256": SHA256,
    "binaries": {name: {"sha256": SHA256} for name in PEER_BINARIES},
    "self_test": exactly("pass"),
}
# The candidate snapshot and the byte-identical rebuild that bind the test binary (#1528).
BINDING_FIELDS = ("source", "test_binary_binding")
BINDING_SCHEMA = {
    "source": {"commit": hex_text(40), "tree": hex_text(40), "head_tree": hex_text(40), "clean": exactly(True)},
    "test_binary_binding": {
        "method": exactly(candidate_binding.METHOD), "package": text, "form": lambda value: value in ("test", "build"),
        "toolchain": text, "sha256": SHA256, "rebuild": exactly("byte-identical"),
        "settings": lambda value: isinstance(value, dict) and all(isinstance(item, str) for pair in value.items() for item in pair)},
}
NATIVE_IDENTITY_SCHEMA = {
    "candidate": hex_text(40), "tree": hex_text(40),
    "go": lambda value: text(value) and GO_RELEASE.fullmatch(value) is not None,
    "kernel": {"system": exactly("Darwin"), "release": text, "version": text, "machine": exactly("arm64")},
    "build_identity_sha256": SHA256, "runner_sha256": SHA256, "peer_driver_sha256": SHA256, "test_binary_sha256": SHA256,
} | BINDING_SCHEMA
# Every identity field except the test binary and its binding, which differ between the
# two receipts by design.
NATIVE_SHARED_IDENTITY = tuple(key for key in NATIVE_IDENTITY_SCHEMA if key not in ("test_binary_sha256", "test_binary_binding"))
NATIVE_RUN_SCHEMA = {"profile": exactly(NATIVE_PROFILE), "status": exactly("pass"), "command": command_line,
                     "started": text, "duration_seconds": nonnegative_number}
NATIVE_RECEIPT_SCHEMAS = {
    "ordinary-control": NATIVE_RUN_SCHEMA | {
        "mode": exactly("ordinary-control"), "policy": exactly("primary-backup"), "controller": exactly("reno"),
        "executed": exactly(EXPECTED), "identity": NATIVE_IDENTITY_SCHEMA | {"peer_binary_sha256": SHA256}},
    "matrix-discovery": NATIVE_RUN_SCHEMA | {
        "mode": exactly("matrix-discovery"), "listed": exactly(DISCOVERY_EXPECTED), "executed": exactly([]),
        "identity": NATIVE_IDENTITY_SCHEMA},
}


def execution_identity(binary, test_binary):
    candidate = os.environ.get("QGF_SOURCE_COMMIT", "")
    tree = os.environ.get("QGF_SOURCE_TREE", "")
    image = os.environ.get("QGF_IMAGE_ID", "")
    if (any(len(value) != 40 or any(c not in "0123456789abcdef" for c in value) for value in (candidate, tree))
            or len(image) != 71 or not image.startswith("sha256:") or any(c not in "0123456789abcdef" for c in image[7:])):
        raise ValueError("matrix execution requires exact QGF_SOURCE_COMMIT, QGF_SOURCE_TREE and QGF_IMAGE_ID")
    version = subprocess.check_output(["go", "version"], text=True, timeout=10).strip()
    if version != "go version go1.27.4 linux/amd64":
        raise ValueError(f"unqualified primary toolchain: {version}")
    return {"candidate": candidate, "tree": tree, "image": image, "go": version,
            "kernel": {"system": platform.system(), "release": platform.release(), "version": platform.version(), "machine": platform.machine()},
            "picoquic": PICOQUIC_PIN, "picotls": PICOTLS_PIN,
            "peer_binary_sha256": digest(binary), "test_binary_sha256": digest(test_binary) if test_binary else None,
            "runner_sha256": digest(__file__), "peer_driver_sha256": digest(Path(__file__).with_name("peer.c"))}


def check_cases(lines, package=PACKAGE, expected=EXPECTED):
    passed = []
    for line in lines:
        event = json.loads(line)
        if event.get("Package") != package:
            continue
        action = event.get("Action")
        if action in ("skip", "fail"):
            raise ValueError(f"{action}: {event.get('Test', package)}")
        # Go names a repeated subtest "<name>#NN"; a repeated expected case is a duplicate, not an extra test.
        renamed = REPEATED_SUBTEST.fullmatch(event.get("Test") or "")
        if renamed and renamed.group(1) in expected:
            raise ValueError(f"duplicate expected case: {event['Test']}")
        if action == "pass" and event.get("Test") in expected:
            passed.append(event["Test"])
    if sorted(passed) != sorted(expected):
        raise ValueError(f"missing or duplicate expected cases: {passed}; required {expected}")


def execution_profile(system, machine):
    """Dispatch the host identity to exactly one profile; there is no fallback."""
    for name, (expected_system, machines) in PROFILES.items():
        if system.lower() == expected_system and machine in machines:
            return name
    raise ValueError(f"no peer execution profile for {system}/{machine}")


def check_prerequisites(binary, system, machine, profile="linux-docker"):
    expected_system, machines = PROFILES[profile]
    if system.lower() != expected_system or machine not in machines:
        raise ValueError("the peer scenarios require Linux amd64" if profile == "linux-docker"
                         else "the darwin-native profile requires Darwin arm64")
    if binary is not None and (not Path(binary).is_file() or not os.access(binary, os.X_OK)):
        raise ValueError(f"missing executable peer binary: {binary}")


def required_executables(profile):
    # The native C adapter writes unbuffered output and the ordinary demo is ready
    # when a bounded Dial succeeds, so Darwin does not need GNU stdbuf.
    return ("go", "stdbuf") if profile == "linux-docker" else ("go",)


def load_build_identity(path, system, machine, binary=None):
    """Read back the native build recipe's record; unknown or malformed fields fail."""
    record = read_record(path, BUILD_IDENTITY_SCHEMA, "build identity")
    if record["platform"]["system"] != system or record["platform"]["machine"] != machine:
        raise ValueError(f"build identity platform does not match {system}/{machine}")
    if record["peer_driver_sha256"] != digest(Path(__file__).with_name("peer.c")):
        raise ValueError("build identity was produced from a different peer.c")
    if binary is not None and digest(binary) not in {entry["sha256"] for entry in record["binaries"].values()}:
        raise ValueError(f"peer binary is not one recorded by the build identity: {binary}")
    return record


def check_test_binary_settings(build_info, goos, goarch, toolchain=None):
    """Require `go version -m` build settings of a picoquic-tagged native test binary.

    When toolchain is given (such as "go1.27.4"), the binary must have been built by it.
    """
    lines = build_info.splitlines()
    built_by = lines[0].rpartition(": ")[2].strip() if lines else ""
    if toolchain is not None and built_by != toolchain:
        raise ValueError(f"test binary was built by {built_by or 'an unknown toolchain'}, not {toolchain}")
    settings = {}
    for line in lines:
        fields = line.strip().split("\t")
        if len(fields) == 2 and fields[0] == "build":
            key, _, value = fields[1].partition("=")
            settings[key] = value
    tags = settings.get("-tags", "").split(",")
    if settings.get("GOOS") != goos or settings.get("GOARCH") != goarch or "picoquic" not in tags:
        raise ValueError(f"test binary is not a picoquic-tagged {goos}/{goarch} build: {settings}")
    return settings


def native_identity(build_identity, binary, test_binary, source=SOURCE):
    candidate = os.environ.get("QGF_SOURCE_COMMIT", "")
    tree = os.environ.get("QGF_SOURCE_TREE", "")
    if not is_hex(candidate, 40) or not is_hex(tree, 40):
        raise ValueError("native execution requires exact QGF_SOURCE_COMMIT and QGF_SOURCE_TREE")
    system, machine = platform.system(), platform.machine()
    load_build_identity(build_identity, system, machine, binary)
    version = subprocess.check_output(["go", "version"], text=True, timeout=10).strip()
    if not version.endswith(" darwin/arm64"):
        raise ValueError(f"native profile requires a darwin/arm64 toolchain: {version}")
    info = subprocess.check_output(["go", "version", "-m", str(test_binary)], text=True, timeout=10)
    check_test_binary_settings(info, "darwin", "arm64", version.split()[2])
    # Before any output or launch: the binary must be the clean candidate's build (#1528).
    bound = candidate_binding.bind(source, candidate, {"test_binary": test_binary}, tree=tree)
    identity = {"candidate": candidate, "tree": tree, "go": version,
                "kernel": {"system": system, "release": platform.release(), "version": platform.version(), "machine": machine},
                "build_identity_sha256": digest(build_identity), "runner_sha256": digest(__file__),
                "peer_driver_sha256": digest(Path(__file__).with_name("peer.c")), "test_binary_sha256": digest(test_binary),
                "source": bound["source"], "test_binary_binding": bound["bindings"]["test_binary"]}
    schema = NATIVE_IDENTITY_SCHEMA
    if binary is not None:
        identity["peer_binary_sha256"] = digest(binary)
        schema = schema | {"peer_binary_sha256": SHA256}
    return check_record(identity, schema, "native identity")


def ordinary_invocation(test_binary=None):
    if test_binary is None:
        command = ["go", "test", "-json", "-tags=picoquic", "-run=^TestPicoquicOrdinaryControl$", "-count=1", "-timeout=90s",
                   "./integrationtests/self", "-version=1"]
    else:
        # An absolute path: a bare name would be looked up on PATH instead of the hashed file.
        command = ["go", "tool", "test2json", "-t", "-p", PACKAGE, str(Path(test_binary).resolve()), "-test.v=test2json",
                   "-test.run=^TestPicoquicOrdinaryControl$", "-test.count=1", "-test.timeout=90s", "-version=1"]
    return command, PACKAGE, EXPECTED


def discovery_command(test_binary):
    return [str(Path(test_binary).resolve()), "-test.list", "^TestPicoquicMultipathMatrix$"]


def check_listing(lines):
    listed = [line.strip() for line in lines if line.strip()]
    if listed != DISCOVERY_EXPECTED:
        raise ValueError(f"matrix discovery listed {listed}; required {DISCOVERY_EXPECTED}")
    return listed


def kill_group(pgid):
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass  # the group already has no members


@contextlib.contextmanager
def sigterm_as_interrupt():
    """While active, SIGTERM raises KeyboardInterrupt, the operator-interrupt unwind path.

    An inherited ignore stays installed, so children still inherit it. The previous
    disposition is restored on exit. Python installs handlers only on the main thread.
    """
    def interrupt(signum, frame):
        raise KeyboardInterrupt("SIGTERM")

    previous = signal.getsignal(signal.SIGTERM)
    if previous is not signal.SIG_IGN:
        signal.signal(signal.SIGTERM, interrupt)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_DFL if previous is None else previous)


def run_group(command, stdout, timeout, env=None, cwd=None):
    """Run one child in its own process group; on any exit or failure, including timeout,
    interrupt or SIGTERM, kill what remains of the group and join the child. Call it from
    the main thread: it installs the SIGTERM conversion while it waits."""
    with sigterm_as_interrupt():
        process = subprocess.Popen(command, env=env, cwd=cwd, stdout=stdout, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            status = process.wait(timeout=timeout)
        except BaseException:
            kill_group(process.pid)
            process.wait()
            raise
        # A child that exits, for example after a crash, can leave peers it never joined.
        kill_group(process.pid)
        return status


def run_bounded(command, env, log_path, timeout):
    """Run one child in its own process group; on any exit or failure, kill what remains of the group and join the child."""
    with Path(log_path).open("w") as log:
        return run_group(command, log, timeout, env=env)


def read_native_receipt(path, mode, where):
    """Read one native receipt back, naming a missing #1528 binding before its shape, then
    require the binding to describe this receipt's candidate, tree and test binary."""
    try:
        identity = json.loads(Path(path).read_text()).get("identity")
    except (OSError, json.JSONDecodeError, AttributeError):
        identity = None  # read_record reports it
    if isinstance(identity, dict) and any(field not in identity for field in BINDING_FIELDS):
        missing = [field for field in BINDING_FIELDS if field not in identity]
        raise ValueError(f"{where} lacks the #1528 candidate binding ({', '.join(missing)}): "
                         "its test binary was never proven to be the candidate's build")
    receipt = read_record(path, NATIVE_RECEIPT_SCHEMAS[mode], where)
    identity = receipt["identity"]
    if identity["source"]["commit"] != identity["candidate"]:
        raise ValueError(f"{where} identity: source commit {identity['source']['commit']} is not the candidate {identity['candidate']}")
    if identity["source"]["tree"] != identity["tree"]:
        raise ValueError(f"{where} identity: source tree {identity['source']['tree']} is not the recorded tree {identity['tree']}")
    if identity["test_binary_binding"]["sha256"] != identity["test_binary_sha256"]:
        raise ValueError(f"{where} identity: the binding names {identity['test_binary_binding']['sha256']}, "
                         f"not the test binary {identity['test_binary_sha256']}")
    return receipt


def check_native(root):
    """Read back the native ordinary-control and discovery receipts; neither substitutes for the other."""
    control, discovery = root / "ordinary-control", root / "matrix-discovery"
    paths = (control / "go-test.jsonl", control / "result.json", discovery / "list.txt", discovery / "result.json")
    if not all(path.is_file() for path in paths):
        raise ValueError(f"missing native receipt: {[str(path) for path in paths if not path.is_file()]}")
    check_cases((control / "go-test.jsonl").read_text().splitlines(), PACKAGE, EXPECTED)
    ordinary = read_native_receipt(control / "result.json", "ordinary-control", "native ordinary-control receipt")
    listed = check_listing((discovery / "list.txt").read_text().splitlines())
    found = read_native_receipt(discovery / "result.json", "matrix-discovery", "native matrix-discovery receipt")
    identities = [ordinary["identity"], found["identity"]]
    if any(identities[0][key] != identities[1][key] for key in NATIVE_SHARED_IDENTITY):
        raise ValueError("native receipts do not share one candidate/toolchain/build identity")
    return {"profile": NATIVE_PROFILE, "status": "pass",
            "ordinary_control": {"executed": EXPECTED, "identity": identities[0]},
            "matrix_discovery": {"listed": listed, "executed": [], "identity": identities[1]},
            "guarantee": "example-level native build, ordinary control and matrix discovery; no multipath executed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--profile", choices=tuple(PROFILES), default="linux-docker",
                        help="explicit execution identity; darwin-native runs only the ordinary control and matrix discovery")
    parser.add_argument("--build-identity", type=Path, help="darwin-native build record from native_build.py")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--smoke", action="store_true", help="run R14's two-path smoke instead of the ordinary control")
    modes.add_argument("--matrix", action="store_true", help="run exactly one R17 scenario/role")
    modes.add_argument("--zero-vectors", action="store_true", help="run the separate negotiated-zero normative/controlled evidence")
    modes.add_argument("--validate-matrix", action="store_true", help="validate the 16 retained independent case receipts")
    modes.add_argument("--discover-matrix", action="store_true", help="list the compiled native matrix without executing it")
    modes.add_argument("--validate-native", action="store_true", help="validate the native ordinary-control and discovery receipts")
    parser.add_argument("--policy", choices=("primary-backup", "aggregate"), default="primary-backup")
    parser.add_argument("--controller", choices=("reno", "bbrv3"), default="reno")
    parser.add_argument("--scenario", choices=MATRIX_SCENARIOS)
    parser.add_argument("--role", choices=("client", "server"))
    parser.add_argument("--test-binary", type=Path)
    parser.add_argument("--source", type=Path,
                        help="darwin-native only: the clean candidate checkout the test binary must rebuild from byte for byte; "
                             "default: the checkout holding this runner")
    args = parser.parse_args()
    native = args.profile == NATIVE_PROFILE
    if args.source is not None and not native:
        parser.error("--source belongs to the darwin-native profile")
    if native and (args.smoke or args.matrix or args.zero_vectors or args.validate_matrix):
        parser.error("darwin-native executes no multipath case before public admission")
    if not native and (args.discover_matrix or args.validate_native or args.build_identity):
        parser.error("matrix discovery, native validation and build identities require --profile darwin-native")
    if args.policy == "aggregate" and (args.controller != "bbrv3" or not (args.matrix or args.validate_matrix)):
        parser.error("aggregate requires the fixed BBR matrix")
    if args.validate_matrix or args.validate_native:
        result = check_native(args.output) if args.validate_native else check_matrix(args.output, args.controller, args.policy)
        with (args.output / ("native-result.json" if args.validate_native else "matrix-result.json")).open("x") as output:
            json.dump(result, output, indent=2)
            output.write("\n")
        print(json.dumps(result))
        return
    if args.controller != "reno" and not args.matrix:
        parser.error("BBR is supported only for the fixed matrix")
    if not args.binary and not args.discover_matrix:
        parser.error("--binary is required for execution")
    if args.discover_matrix and args.binary:
        parser.error("matrix discovery launches no peer")
    if not args.matrix and (args.scenario or args.role):
        parser.error("case selection requires --matrix")
    if args.test_binary and not (args.matrix or args.zero_vectors or native):
        parser.error("--test-binary requires --matrix or --zero-vectors")
    if args.matrix and (not args.scenario or not args.role):
        parser.error("--matrix requires --scenario and --role")
    if native and (not args.test_binary or not args.build_identity):
        parser.error("darwin-native requires --test-binary and --build-identity")
    if native:
        # Resolve once, so the inspected, hashed, recorded and launched files are the same.
        args.test_binary, args.build_identity = args.test_binary.resolve(), args.build_identity.resolve()
        args.binary = str(Path(args.binary).resolve()) if args.binary else None
    check_prerequisites(args.binary, platform.system(), platform.machine(), args.profile)
    for executable in required_executables(args.profile):
        if shutil.which(executable) is None:
            raise ValueError(f"missing prerequisite: {executable}")
    if args.test_binary and (not args.test_binary.is_file() or not os.access(args.test_binary, os.X_OK)):
        raise ValueError(f"missing executable test binary: {args.test_binary}")
    if native:
        identity = native_identity(args.build_identity, args.binary, args.test_binary, args.source or SOURCE)
    else:
        identity = execution_identity(args.binary, args.test_binary) if args.matrix or args.zero_vectors else None
    args.output.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    before = time.monotonic()
    if args.discover_matrix:
        command = discovery_command(args.test_binary)
        attempt = {"profile": args.profile, "mode": "matrix-discovery", "expected": DISCOVERY_EXPECTED,
                   "identity": identity, "command": command, "started": started}
        (args.output / "attempt.json").write_text(json.dumps(attempt, indent=2) + "\n")
        status = run_bounded(command, os.environ, args.output / "list.txt", 30)
        if status != 0:
            raise ValueError(f"matrix discovery exited {status}; see {args.output / 'list.txt'}")
        listed = check_listing((args.output / "list.txt").read_text().splitlines())
        result = {"profile": args.profile, "mode": "matrix-discovery", "status": "pass", "listed": listed, "executed": [],
                  "identity": identity, "command": command, "started": started, "duration_seconds": time.monotonic() - before}
        (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))
        return
    env = os.environ | {"PICOQUIC_BINARY": str(Path(args.binary).resolve()), "PICOQUIC_LOG_DIR": str(args.output.resolve()),
                        "PICOQUIC_CONTROLLER": args.controller, "PICOQUIC_POLICY": args.policy}
    command, package, expected = ordinary_invocation(args.test_binary if native else None)
    if args.smoke:
        command = ["go", "test", "-json", "-tags=picoquic", "-run=^TestPicoquicMultipathSmoke$", "-count=1", "-timeout=90s", "."]
        package, expected = SMOKE_PACKAGE, SMOKE_EXPECTED
    if args.matrix:
        command, expected = matrix_invocation(args.scenario, args.role, args.test_binary, args.controller)
        package = SMOKE_PACKAGE
    if args.zero_vectors:
        expression = "^TestMultipathNegotiatedZero(Vectors|ControlledPeer)$"
        command = ["go", "test", "-json", "-tags=picoquic", f"-run={expression}", "-count=1", "-timeout=90s", "."]
        if args.test_binary:
            command = ["go", "tool", "test2json", "-t", "-p", SMOKE_PACKAGE, str(args.test_binary),
                       "-test.v=test2json", f"-test.run={expression}", "-test.count=1", "-test.timeout=90s"]
        package, expected = SMOKE_PACKAGE, ZERO_EXPECTED
    attempt = {"policy": args.policy, "controller": args.controller, "expected": expected, "identity": identity, "command": command, "started": started}
    if native:
        attempt = {"profile": args.profile, "mode": "ordinary-control"} | attempt
    (args.output / "attempt.json").write_text(json.dumps(attempt, indent=2) + "\n")
    status = run_bounded(command, env, args.output / "go-test.jsonl", 120)
    if status != 0:
        raise ValueError(f"peer control exited {status}; see {args.output / 'go-test.jsonl'}")
    check_cases((args.output / "go-test.jsonl").read_text().splitlines(), package, expected)
    result = {"policy": args.policy, "controller": args.controller, "executed": expected, "status": "pass", "identity": identity,
              "command": command, "started": started, "duration_seconds": time.monotonic() - before}
    if native:
        result = {"profile": args.profile, "mode": "ordinary-control"} | result
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
