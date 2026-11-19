#!/usr/bin/env python3
"""MP-MAC C4 topology comparison: one relay, server and client per observation, read back
through the Go verify role. Observations are recorded side by side without a verdict; a
missing, refused or misaccounted observation fails the run."""

import argparse
import contextlib
import json
import math
import os
import platform
import resource
import select
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import ordinary_cost as c1

VERSION = 1
SPEC_ENV = "TOPOLOGY_COMPARISON_SPEC"
ROLE_TEST = "TestTopologyComparisonRole"
TOPOLOGIES = {"disjoint": ("a", "b"), "unequal": ("a", "b"), "shared": ("a", "b", "competitor")}
# The closed arm inventory of topology_comparison_fixture_test.go, which owns its plans;
# the driver keeps only what refusal before launch needs.
ARMS = {
    "single-a": {"multipath": False},
    "single-b": {"multipath": False},
    "pair": {"multipath": False},
    "primary-backup": {"multipath": True},
    "aggregate": {"multipath": True, "controller": "bbrv3"},
}
CONTROLLERS = ("reno", "bbrv3")
# (warmup, window) seconds. Q1 selects any collection protocol; neither mode is a campaign.
MODES = {"smoke": (1, 5), "diagnostic": (10, 60)}
BASE_SEED = 1493
# The Go client dials 3 s before the timeline's start; the extra seconds let the server bind.
SETUP_S = 5
# The roles read at half the 2 s drain and close at its end.
DRAIN_S = 2
ROLE_SLACK_S = 30
RELAY_READY_S = 10
RELAY_CPU_SOURCE = ("udprelay process user+system time, RUSAGE_CHILDREN across its reap; "
                    "its whole lifetime including setup and drain, not window CPU")
# What each profile's observations are evidence of; neither qualifies Darwin.
EVIDENCE_CLASS = {
    c1.LINUX: "linux public-profile functional control: every arm through public interfaces",
    c1.DARWIN: "darwin ordinary-arm smoke: multipath arms refused until public Darwin admission (Q2)",
}
NOT_JUDGED = ("topology comparison observations are apparatus records; no throughput, fairness or "
              "statistical criterion applies, and Q1 selects any comparison protocol")
METRIC_BOUNDARIES = {
    "useful_bytes": "receiver-counted focal STREAM bytes read in the window plus first-copy DATAGRAM bytes sent in the window",
    "object_completion": "receiver time from an object's send-start timestamp to the receiver's read returning EOF on the complete object; that EOF falls in the window",
    "max_receive_gap_ns": "longest part of the window in which a flow's receiver got nothing useful",
    "relay_drops": "relay queue drops and backlog overflow per route, as its record counts them",
    "relay_cpu": RELAY_CPU_SOURCE,
    "self_cpu": "each role's own getrusage user+system time over the window",
}


def refusal(platform_profile, arm, controller):
    """Why the arm cannot run on the profile, or None. The Go roles refuse the same."""
    if arm not in ARMS:
        return f"unknown arm {arm}"
    if controller not in CONTROLLERS:
        return f"unknown controller {controller}"
    if ARMS[arm]["multipath"] and not c1.PROFILES[platform_profile]["negotiated_multipath"]:
        return f"arm {arm} needs negotiated multipath, which {platform_profile} does not admit publicly"
    if ARMS[arm].get("controller", controller) != controller:
        return f"arm {arm}: aggregate multipath requires bbrv3"
    return None


def role_command(binary, timeout_s):
    return [str(binary), f"-test.run=^{ROLE_TEST}$", "-test.count=1", "-test.v", f"-test.timeout={math.ceil(timeout_s)}s"]


def check_role_log(role, output):
    if output.count(f"--- PASS: {ROLE_TEST}") != 1:
        raise ValueError(f"{role} must pass exactly once:\n{output[-2000:]}")


@contextlib.contextmanager
def deferred_interrupts():
    """C1's DeferredInterrupts, plus: a cancellation recorded while a failure was already
    leaving still cancels once every owned child is reaped, with that failure as its cause."""
    interrupts = c1.DeferredInterrupts()
    try:
        with interrupts:
            yield interrupts
    except Exception as error:
        if interrupts.pending:
            raise KeyboardInterrupt(signal.Signals(interrupts.pending[0]).name) from error
        raise


def run_role(binary, env, spec, log_path, timeout_s, launched):
    """A short synchronous role: relay-config or verify. Its child is killed and reaped on
    any exit from the wait, an interrupt or timeout included."""
    with deferred_interrupts() as interrupts:
        with log_path.open("w") as log:
            process = subprocess.Popen(role_command(binary, timeout_s), env=dict(env, **{SPEC_ENV: json.dumps(spec)}),
                                       stdout=log, stderr=subprocess.STDOUT)
        launched.setdefault("test", str(binary))
        try:
            with interrupts.interruptible():  # the only point an operator interrupt raises
                process.wait(timeout=timeout_s)
        finally:
            if process.returncode is None:
                process.kill()
                process.wait()
    if process.returncode != 0:
        raise ValueError(f"{spec['role']} exit {process.returncode}:\n{log_path.read_text()[-2000:]}")
    check_role_log(spec["role"], log_path.read_text())


def free_port():
    """An ephemeral IPv4 loopback UDP port for the server, released for the server to bind."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def read_ready(process, deadline):
    """The relay's one ready line, read without blocking past deadline."""
    data = b""
    while b"\n" not in data:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("the relay did not report its fronts in time")
        ready, _, _ = select.select([process.stdout], [], [], remaining)
        if not ready:
            continue
        chunk = os.read(process.stdout.fileno(), 4096)
        if not chunk:
            raise ValueError(f"the relay exited before reporting its fronts (exit {process.poll()})")
        data += chunk
    line, rest = data.split(b"\n", 1)
    if rest:
        raise ValueError("the relay wrote more than its ready line")
    return json.loads(line)


def check_ready(ready, topology):
    """The ready line names exactly the topology's routes, each bound on IPv4 loopback."""
    if not isinstance(ready, dict) or set(ready) != {"version", "fronts"} or ready["version"] != 1:
        raise ValueError(f"unexpected relay ready line {ready}")
    fronts = ready["fronts"]
    if not isinstance(fronts, dict) or set(fronts) != set(TOPOLOGIES[topology]):
        raise ValueError(f"relay fronts {fronts} are not the {topology} routes {TOPOLOGIES[topology]}")
    for route, front in fronts.items():
        host, _, port = str(front).rpartition(":")
        if host != "127.0.0.1" or not port.isdigit() or not 0 < int(port) < 65536:
            raise ValueError(f"route {route} front {front} is not bound on 127.0.0.1")
    return fronts


def check_observation(observation, expected, platform_profile):
    """The verify role validated the comparison; this checks that the observation is the one
    requested and carries the C1 metrics the summary reads."""
    if not isinstance(observation, dict) or observation.get("version") != VERSION:
        raise ValueError(f"observation version {observation.get('version') if isinstance(observation, dict) else None}, want {VERSION}")
    identity = observation.get("identity") or {}
    for key in ("topology", "arm", "controller", "seed", "server"):
        if identity.get(key) != expected[key]:
            raise ValueError(f"observation {key} {identity.get(key)!r} is not the requested {expected[key]!r}")
    goos, goarch = c1.PROFILES[platform_profile]["identity"]
    if observation.get("platform") != {"profile": platform_profile, "goos": goos, "goarch": goarch}:
        raise ValueError(f"observation platform {observation.get('platform')} is not {platform_profile}")
    server, client = observation.get("server") or {}, observation.get("client") or {}
    for role, record in (("server", server), ("client", client)):
        if c1.check_metric(f"{role} self_cpu", record.get("self_cpu"), "ns") is None:
            raise ValueError(f"{role} self_cpu is unavailable; the window has no CPU evidence")
    if c1.check_metric("peak_rss_end", server.get("peak_rss_end"), c1.PROFILES[platform_profile]["rss_unit"]) is None:
        raise ValueError("peak_rss_end is unavailable")
    if c1.check_metric("useful_bytes", server.get("useful_bytes"), "bytes") is None:
        raise ValueError("useful_bytes is unavailable")
    for label, flow in (server.get("flows") or {}).items():
        for key in ("datagram_latency", "object_completion"):
            check_latency(f"{label} {key}", flow.get(key) if isinstance(flow, dict) else None)
    if not isinstance(observation.get("workload_failures"), list):
        raise ValueError("observation lacks its workload failures")
    if not isinstance(observation.get("relay"), dict) or observation["relay"].get("config", {}).get("kind") != expected["topology"]:
        raise ValueError("observation lacks its relay record")


def check_latency(name, latency):
    """A latency summary states its sample count; an empty one is a recorded zero count."""
    if not isinstance(latency, dict) or type(latency.get("count")) is not int or latency["count"] < 0:
        raise ValueError(f"{name}: latency summary needs a nonnegative integer sample count")
    for key in ("p50_us", "p99_us", "max_us"):
        if type(latency.get(key)) not in (int, float):
            raise ValueError(f"{name}: latency summary needs {key}")


def check_relay_cpu(metric):
    if c1.check_metric("relay_cpu", metric, "ns") is None or metric["source"] != RELAY_CPU_SOURCE:
        raise ValueError("relay_cpu must be the driver's observed relay process CPU")


def run_observation(test_binary, relay_binary, directory, topology, arm, controller, seed,
                    platform_profile, warmup_s, window_s, timeout_s, record=None):
    """One observation. Every launched child (relay, server, client) is terminated and reaped,
    even after a partial launch, a failure or an interrupt; the relay's CPU is its own."""
    record = record if record is not None else {}
    record["launched"] = launched = {}  # each executable, once a child of it exists
    directory.mkdir(parents=True, exist_ok=False)
    env = {key: value for key, value in os.environ.items() if not key.startswith("QUIC_GO_") and key != SPEC_ENV}
    base = {"topology": topology, "arm": arm, "controller": controller, "seed": seed,
            "server": f"127.0.0.1:{free_port()}"}
    begun = time.monotonic()
    deadline = begun + timeout_s
    try:
        observation = observe(test_binary, relay_binary, directory, env, base, platform_profile,
                              warmup_s, window_s, timeout_s, deadline, record, launched)
        if time.monotonic() > deadline:
            raise ValueError("the observation was accepted only after its deadline")
    finally:
        # Every attempt, failed ones included, charges its host time through readback.
        record["occupied_s"] = time.monotonic() - begun
    record["observation"] = observation
    return record


def observe(test_binary, relay_binary, directory, env, base, platform_profile, warmup_s, window_s,
            timeout_s, deadline, record, launched):
    topology, arm = base["topology"], base["arm"]
    processes, usage = {}, {}
    relay_cpu = {"value": None, "unit": "ns", "source": RELAY_CPU_SOURCE, "available": False,
                 "reason": "the relay did not exit normally"}
    config = directory / "relay-config.json"
    run_role(test_binary, env, dict(base, role="relay-config", output=str(config)), directory / "relay-config.log",
             max(1, deadline - time.monotonic()), launched)

    def reap(role, process, timeout=None):
        # Only this function reaps children, so each RUSAGE_CHILDREN delta is one child's.
        previous = resource.getrusage(resource.RUSAGE_CHILDREN)
        try:
            process.wait(timeout=timeout)
        finally:
            current = resource.getrusage(resource.RUSAGE_CHILDREN)
            usage[role] = usage.get(role, 0) + (current.ru_utime + current.ru_stime - previous.ru_utime - previous.ru_stime)

    spec = None
    with deferred_interrupts() as interrupts:
        try:
            with (directory / "relay.log").open("w") as log:
                relay = subprocess.Popen([str(relay_binary), "-config", str(config), "-record", str(directory / "relay.json")],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, env=env)
            processes["relay"] = relay
            launched["relay"] = str(relay_binary)
            with interrupts.interruptible():
                fronts = check_ready(read_ready(relay, min(deadline, time.monotonic() + RELAY_READY_S)), topology)
            spec = dict(base, fronts=fronts, start_at_unix_ns=time.time_ns() + SETUP_S * 10**9,
                        warmup_ns=warmup_s * 10**9, window_ns=window_s * 10**9)
            for role in ("server", "client"):
                role_spec = dict(spec, role=role, output=str(directory / f"{role}.json"))
                with (directory / f"{role}.log").open("w") as log:
                    processes[role] = subprocess.Popen(role_command(test_binary, timeout_s),
                                                       env=dict(env, **{SPEC_ENV: json.dumps(role_spec)}),
                                                       stdout=log, stderr=subprocess.STDOUT)
            for role in ("server", "client"):
                with interrupts.interruptible():  # the only points an operator interrupt raises
                    reap(role, processes[role], timeout=max(0, deadline - time.monotonic()))
                if processes[role].returncode != 0:
                    raise ValueError(f"{topology}/{arm} {role} exit {processes[role].returncode}")
            relay.stdin.close()  # end of input: the relay closes, joins and publishes its record
            with interrupts.interruptible():
                reap("relay", relay, timeout=max(0, deadline - time.monotonic()))
            if relay.returncode != 0:
                raise ValueError(f"relay exit {relay.returncode}")
            relay_cpu = {"value": round(usage["relay"] * 1e9), "unit": "ns", "source": RELAY_CPU_SOURCE, "available": True}
        finally:
            # Not interruptible: kill every live child before waiting on any, keep their facts.
            try:
                for process in processes.values():
                    if process.returncode is None:
                        process.kill()
                for role, process in processes.items():
                    if process.returncode is None:
                        reap(role, process)
            finally:
                for process in processes.values():
                    for pipe in (process.stdin, process.stdout):
                        if pipe and not pipe.closed:
                            pipe.close()
                record.update(topology=topology, arm=arm, controller=base["controller"], seed=base["seed"],
                              platform_profile=platform_profile, process_cpu_s=usage, relay_cpu=relay_cpu,
                              exit={role: process.returncode for role, process in processes.items()})
    for role in ("server", "client"):
        check_role_log(role, (directory / f"{role}.log").read_text())
    check_relay_cpu(relay_cpu)
    observation_path = directory / "observation.json"
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError("no time remains in the observation's deadline for verification")
    run_role(test_binary, env, dict(spec, role="verify", output=str(observation_path), relay_record=str(directory / "relay.json"),
                                    server_result=str(directory / "server.json"), client_result=str(directory / "client.json")),
             directory / "verify.log", remaining, launched)

    def reject_nonfinite(value):
        raise ValueError(f"nonfinite JSON number {value}")
    observation = json.loads(observation_path.read_text(), parse_constant=reject_nonfinite)
    check_observation(observation, base, platform_profile)
    return observation


def sampled(latency):
    """A latency summary with its sample count, or None when it has no samples: the
    producer reports zero percentiles for an empty histogram."""
    if latency["count"] == 0:
        return None
    return {key: latency[key] for key in ("count", "p50_us", "p99_us", "max_us")}


def summarize(record):
    """One observation's figures, side by side with the others, without a verdict."""
    observation = record["observation"]
    flows = observation["server"]["flows"]
    focal = {label: flow for label, flow in flows.items() if label != "competitor"}
    summary = {
        "topology": record["topology"], "arm": record["arm"], "controller": record["controller"],
        "focal_stream_bytes": sum(flow["stream_useful_bytes"] for flow in focal.values()),
        "focal_datagram_bytes": sum(flow["datagram_useful_bytes"] for flow in focal.values()),
        "useful_bytes": observation["server"]["useful_bytes"]["value"],
        # Each flow's own figures: an arm with two focal connections has two populations.
        "flows": {label: {"stream_useful_bytes": flow["stream_useful_bytes"],
                          "datagram_useful_bytes": flow["datagram_useful_bytes"],
                          "max_receive_gap_ns": flow["max_receive_gap_ns"],
                          "object_completion": sampled(flow["object_completion"]),
                          "datagram_latency": sampled(flow["datagram_latency"])}
                  for label, flow in sorted(flows.items())},
        "relay_drops": {route["name"]: {"dropped": route["forward"]["dropped"],
                                        "overflow": route["forward"]["overflow"] + route["reverse"]["overflow"]}
                        for route in observation["relay"]["routes"]},
        "relay_cpu_ns": record["relay_cpu"]["value"],
        "self_cpu_ns": {role: observation[role]["self_cpu"]["value"] for role in ("server", "client")},
        "workload_failures": observation["workload_failures"],
    }
    if record["topology"] == "shared":
        # A competitor that delivered nothing has no flow record; the verifier reports that
        # as a workload failure, and the run's other figures still stand.
        competitor = flows.get("competitor", {}).get("stream_useful_bytes", 0)
        total = competitor + summary["focal_stream_bytes"]
        # The Reno competitor's share of the shared bottleneck's STREAM delivery: an observation.
        summary.update(competitor_stream_bytes=competitor, competitor_share=competitor / total if total else None)
    return summary


def check_host(system, machine, platform_profile):
    if (system, machine) != c1.PROFILES[platform_profile]["host"]:
        raise RuntimeError(f"the {platform_profile} profile needs {' '.join(c1.PROFILES[platform_profile]['host'])}, not {system} {machine}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-binary", required=True, help="the root test binary built with -tags ordinarycost")
    parser.add_argument("--relay-binary", required=True, help="the built interop/multipath/relay/cmd/udprelay executable")
    parser.add_argument("--candidate", required=True, help="the exact 40-character product commit under observation")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--platform-profile", choices=sorted(c1.PROFILES), default=c1.LINUX)
    parser.add_argument("--topology", required=True, choices=sorted(TOPOLOGIES))
    parser.add_argument("--arm", required=True, action="append", choices=list(ARMS),
                        help="repeatable; the arms run once each, in the order given")
    parser.add_argument("--controller", choices=CONTROLLERS, default="bbrv3",
                        help="the focal connections' controller; the shared topology's competitor is always Reno")
    parser.add_argument("--mode", choices=sorted(MODES), default="smoke")
    parser.add_argument("--seed", type=int, default=BASE_SEED)
    parser.add_argument("--timeout-seconds", required=True, type=float,
                        help="maximum duration of one observation, including setup, drain and cleanup")
    args = parser.parse_args(argv)
    if len(set(args.arm)) != len(args.arm):
        parser.error("each arm runs once")
    for arm in args.arm:
        reason = refusal(args.platform_profile, arm, args.controller)
        if reason:
            parser.error(reason)
    if len(args.candidate) != 40 or any(c not in "0123456789abcdef" for c in args.candidate):
        parser.error("--candidate must be a full lowercase commit SHA")
    warmup, window = MODES[args.mode]
    if args.timeout_seconds < SETUP_S + warmup + window + DRAIN_S + 10:
        parser.error("--timeout-seconds does not cover setup, warmup, window, drain and cleanup")
    check_host(platform.system(), platform.machine(), args.platform_profile)
    binaries = {"test": c1.binary_identity(args.test_binary), "relay": c1.binary_identity(args.relay_binary)}
    args.output.mkdir(parents=True, exist_ok=False)
    identity = {
        "version": VERSION, "candidate": args.candidate, "binaries": binaries, "platform_profile": args.platform_profile,
        "topology": args.topology, "arms": args.arm, "controller": args.controller, "mode": args.mode, "seed": args.seed,
        "warmup_s": warmup, "window_s": window, "per_observation_timeout_s": args.timeout_seconds,
        "kernel": platform.platform(), "uname": " ".join(platform.uname()), "go": c1.GO_VERSION,
        "pinning": "none: Q1 selects any CPU placement", "metric_boundaries": METRIC_BOUNDARIES,
        "evidence_class": EVIDENCE_CLASS[args.platform_profile],
    }
    if args.platform_profile == c1.DARWIN:
        identity["macos"] = platform.mac_ver()[0]
    (args.output / "identity.json").write_text(json.dumps(identity, indent=2) + "\n")

    def interrupt_on_sigterm(signum, frame):
        raise KeyboardInterrupt("SIGTERM")

    previous_sigterm = signal.signal(signal.SIGTERM, interrupt_on_sigterm)
    summary = {"version": VERSION, "passed": False, "judged": False, "judgment": NOT_JUDGED, "mode": args.mode,
               "platform_profile": args.platform_profile, "evidence_class": EVIDENCE_CLASS[args.platform_profile],
               "topology": args.topology, "observations": []}
    try:
        for arm in args.arm:
            # The attempt is identifiable before setup, so any failure leaves a terminal row.
            record = {"status": "started", "topology": args.topology, "arm": arm, "controller": args.controller,
                      "seed": args.seed, "platform_profile": args.platform_profile}

            def failed(error):
                record.update(status="failed", error=f"{type(error).__name__}: {error}")
                if error.__cause__ is not None:
                    record["cause"] = f"{type(error.__cause__).__name__}: {error.__cause__}"
                summary["observations"].append({"topology": args.topology, "arm": arm, "status": "failed",
                                                "error": record["error"], **({"cause": record["cause"]} if "cause" in record else {})})
            try:
                run_observation(binaries["test"]["path"], binaries["relay"]["path"], args.output / args.topology / arm, args.topology, arm,
                                args.controller, args.seed, args.platform_profile, warmup, window, args.timeout_seconds, record)
                record["status"] = "succeeded"
                summary["observations"].append(dict(summarize(record), status=record["status"]))
            except Exception as error:
                failed(error)
            except KeyboardInterrupt as error:
                failed(error)
                raise  # cancellation stops the run: no later arm launches
            finally:
                # Publication completes before a cancellation that arrives during it stops the run.
                with c1.DeferredInterrupts(), (args.output / "observations.jsonl").open("a") as file:
                    file.write(json.dumps(record) + "\n")
        summary["passed"] = (len(summary["observations"]) == len(args.arm)
                             and all("error" not in o and not o["workload_failures"] for o in summary["observations"]))
    except KeyboardInterrupt as error:
        summary.update(passed=False, error=f"KeyboardInterrupt: {error}")
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        with c1.DeferredInterrupts():
            (args.output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    print(f"done: {args.topology} {' '.join(args.arm)}, passed {summary['passed']}", flush=True)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
