#!/usr/bin/env python3
"""R18 ordinary-peer cost: a missing or misaccounted case is a failed claim, not a product result."""

import argparse
import contextlib
import json
import hashlib
import math
import resource
import signal
import sys
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import statistics
import subprocess
import time

import candidate_binding

GO_VERSION = "go1.27.4"
ROUNDS = 3
WARMUP_S = 10
WINDOW_S = 60
SETUP_S = 5
BASE_SEED = 1038
DISABLE_GSO = {"QUIC_GO_DISABLE_GSO": "true"}
CELLS = {
    "stream-gso-on": {"env": {}},
    "stream-gso-off": {"env": DISABLE_GSO},
    "datagram-batch-on": {"env": {}},
    "datagram-batch-off": {"env": DISABLE_GSO},
    "mixed-bulk": {"env": {}},
    "stateless-pressure": {"env": {}},
}
# The native Darwin arm64 profile's workloads. Darwin has no wire GSO, and QUIC_GO_DISABLE_GSO
# does not change its sends, so acceleration arms would repeat one wiring.
NATIVE_CELLS = {
    "stream": {"env": {}},
    "datagram": {"env": {}},
    "mixed-bulk": {"env": {}},
    "stateless-pressure": {"env": {}},
}
LINUX, DARWIN = "linux-amd64", "darwin-arm64"
# The collectors of the C1 metrics, as the Go producers name them. Readback admits no other
# source for these fields; consumers that add metrics pin their own producers' sources.
CPU_SOURCE = "getrusage(RUSAGE_SELF) user+system time, window end minus start"
LOST_SOURCE = "ConnectionStats().PacketsLost"
USEFUL_SOURCE = "receiver-counted application bytes in the window, every flow"
# A platform profile owns its inventory, host tuple, RSS unit and collectors, and what it can claim.
# Both profiles admit multipath publicly (Darwin on Darwin 27 arm64, protocol D14), so an
# opted-in arm grants through Transport.ConfigureMultipathIOV1 and advertises multipath.
PROFILES = {
    LINUX: {"host": ("Linux", "x86_64"), "identity": ("linux", "amd64"), "cells": CELLS, "rss_unit": "kB",
            "sources": {"self_cpu": CPU_SOURCE, "peak_rss": "/proc/self/status VmHWM",
                        "packets_lost_metric": LOST_SOURCE, "useful_bytes": USEFUL_SOURCE},
            "gso": True, "negotiated_multipath": True},
    DARWIN: {"host": ("Darwin", "arm64"), "identity": ("darwin", "arm64"), "cells": NATIVE_CELLS, "rss_unit": "bytes",
             "sources": {"self_cpu": CPU_SOURCE, "peak_rss": "getrusage(RUSAGE_SELF).ru_maxrss",
                         "packets_lost_metric": LOST_SOURCE, "useful_bytes": USEFUL_SOURCE},
             "gso": False, "negotiated_multipath": True},
}
RSS_SCALE = {"kB": 1024, "bytes": 1}
NATIVE_NOT_JUDGED = ("native observations are semantic smoke records; Linux thresholds and foreign-CPU "
                     "arithmetic do not transfer, and Q1 selects any comparative protocol")
# The Reno thresholds judge Reno pairs and the historical BBR stateless-pressure diagnostic.
# A newly matched BBR workload reports its ratios as observations, not as a verdict.
BBR_NOT_JUDGED = ("BBR smoke/diagnostic ratios are observations; the accepted thresholds are Reno's, "
                  "and only the historical stateless-pressure BBR diagnostic keeps their verdict")
# MP-MAC C2's negotiated lifecycle-memory record: three phase samples of one connection,
# in order, from public interfaces only. The retired sample's path state is exactly the
# qualifying state the run names, retained or closed; Q1 binds one for both sides of a
# comparison. Backup and retirement compare with this connection's negotiated idle.
LIFECYCLE = "lifecycle-memory"
# Both role records carry this format; readback admits no other revision.
LIFECYCLE_FORMAT = "mp-mac-c2-lifecycle-memory/1"
PATH_ID_LIMIT = 2**32  # the producer's uint32 path and wire IDs
LIFECYCLE_PHASES = ("negotiated-idle", "validated-backup", "retired")
LIFECYCLE_RETIRED = ("retained", "closed")
LIFECYCLE_TIMEOUT_S = 30
LIFECYCLE_BOUNDARIES = {
    "go_heap_live": "Go heap marked live by a forced runtime.GC() in the client role at the phase; not resident memory",
    "peak_rss": "the client role's lifetime peak RSS when the phase was sampled; never memory held at that phase",
    "transport_detachment": "Conn.WaitTransportDetachedV1 for the retired path's transport; not a grant join",
    "grant_joins": "Transport.WaitMultipathIOStoppedV1 after Transport.Close, per transport; not a detachment",
}
# The method and interface labels the Go roles record. The forced-GC heap method must be
# the same on every sample, so that both sides of a comparison read one quantity.
LIFECYCLE_BOUNDARY_SOURCES = {
    "go_heap_live": "runtime/metrics /gc/heap/live:bytes after a forced runtime.GC()",
    "transport_detachment": "Conn.WaitTransportDetachedV1",
    "grant_joins": "Transport.WaitMultipathIOStoppedV1 after Transport.Close",
}
LIFECYCLE_NOT_JUDGED = ("lifecycle memory records are readiness observations; Q1 binds any comparison, "
                        "its qualifying retirement state and its thresholds")
SUDO = "/usr/bin/sudo"
SAMPLER_WRAPPER = "/usr/local/libexec/quicquic-powermetrics"  # the owner's root-owned install
# The bounded wait for the sampler to exit once its standard input closes. It covers the
# wrapper's own grace before it kills powermetrics.
SAMPLER_STOP_S = 5
# Allowance for the driver's own launch/stop timing around the sampler's elapsed sum.
SAMPLER_SLACK_S = 0.05
HOST_STATUSES = ("observed", "unavailable", "inconclusive")
CONTROL, OPTED_IN = "unregistered", "opted-in"
# Accepted product thresholds, section "Accepted product thresholds" of the Reno plan.
GOODPUT_FLOOR = 0.95
CPU_CEILING = 1.10
LATENCY_FACTOR = 1.10
LATENCY_ALLOWANCE_US = 1000.0
# "Bounded memory" operationalized before data: the high-water mark may not keep climbing.
MEMORY_GROWTH_CEILING = 1.10
# Foreign CPU, as a share of one core, that flags an observation. Decided before data
# from the #742 rule of 0.3 CPU-seconds per 10 s, at a looser share for a longer run.
FOREIGN_SHARE_LIMIT = 0.05
MAX_RERUN_PAIRS = 3
QUIET_WAIT_LIMIT_S = 7200
SERVER_CPUS, CLIENT_CPUS = "8-11", "12-15"
FIXTURE_CPUS = list(range(8, 16)) + list(range(24, 32))
HOST_BUSY_PATTERN = "[R]unner.Worker|[t]ransfer.test|qemu.*guest=[i]nfra-garm|[n]ativerig"
QUIET_BUSY_SHARE = 0.05
SERVER_ADDRESS = "127.0.0.1:47438"
METRIC_BOUNDARIES = {
    "application_send_call": "elapsed Stream.Write / SendDatagram call time; neither native return nor peer delivery",
    "control": "application echo round trip",
    "cpu_profile": "sampled CPU across the entire role process, including setup, warmup and cleanup; not window CPU",
    "useful_bytes": "receiver-counted application content within the measurement window",
    "self_cpu": "each role's own getrusage user+system time over the window; per process, not host CPU",
    "host_activity": "optional native powermetrics cluster activity over the sampler's lifetime; never a quiet-host verdict",
}


def schedule_cells(cells=None):
    """The campaign's cells: the whole inventory, or the named subset of it that an
    affected-cell revalidation reruns."""
    inventory = list(CELLS)
    if cells is None:
        return inventory
    if not cells or any(cell not in inventory for cell in cells):
        raise ValueError(f"revalidation cells {cells} are not in the inventory")
    return [cell for cell in inventory if cell in cells]


def schedule(cells=None):
    """The fixed (cell, round, profile, seed) instances. A pair shares its seed, and a
    revalidated cell keeps its seeds."""
    instances = []
    for index, cell in enumerate(CELLS):
        if cell not in schedule_cells(cells):
            continue
        for round_ in range(ROUNDS):
            order = (CONTROL, OPTED_IN) if round_ % 2 == 0 else (OPTED_IN, CONTROL)
            seed = BASE_SEED + 100 * index + round_
            instances += [(cell, round_, profile, seed) for profile in order]
    return instances


def flows(record, label):
    return [flow for flow in record["client"]["flows"] if flow["label"] == label]


def check_metric(name, metric, unit):
    """A metric names its unit and producer; an unavailable metric has no value, not zero."""
    if (not isinstance(metric, dict) or metric.get("unit") != unit
            or not isinstance(metric.get("source"), str) or not metric["source"]):
        raise ValueError(f"{name}: metric needs unit {unit} and a source")
    value, available = metric.get("value"), metric.get("available")
    if available is True:
        if type(value) is not int or value < 0:
            raise ValueError(f"{name}: available metric needs a nonnegative integer value")
    elif available is False:
        if value is not None or not metric.get("reason"):
            raise ValueError(f"{name}: unavailable metric needs no value and a reason")
    else:
        raise ValueError(f"{name}: metric availability is not stated")
    return value


def check_source(name, metric, platform_profile, field):
    """A C1 metric names its platform profile's collector, available or not."""
    expected = PROFILES[platform_profile]["sources"][field]
    if metric["source"] != expected:
        raise ValueError(f"{name}: source must be {expected!r} on {platform_profile}, not {metric['source']!r}")


def check_rss(name, metric, platform_profile):
    """A peak-RSS reading from the platform's collector in its unit, with its normalized bytes."""
    unit = PROFILES[platform_profile]["rss_unit"]
    if not isinstance(metric, dict) or metric.get("unit") != unit:
        raise ValueError(f"{name}: RSS unit must be {unit} on {platform_profile}")
    value = check_metric(name, metric, unit)
    check_source(name, metric, platform_profile, "peak_rss")
    if value is None or metric.get("bytes") != value * RSS_SCALE[unit]:
        raise ValueError(f"{name}: RSS bytes do not normalize the raw {unit} reading")
    return value


def check_identity(record, platform_profile):
    goos, goarch = PROFILES[platform_profile]["identity"]
    expected = {"profile": platform_profile, "goos": goos, "goarch": goarch}
    for role in ("server", "client"):
        if record[role].get("platform") != expected:
            raise ValueError(f"{role}: native identity {record[role].get('platform')} is not {expected}")


def check_metrics(record, platform_profile, controller):
    server, client = record["server"], record["client"]
    for role in (server, client):
        cpu = check_metric("self_cpu", role.get("self_cpu"), "ns")
        check_source("self_cpu", role["self_cpu"], platform_profile, "self_cpu")
        seconds = role.get("window_cpu_s")
        # The producer marks only a negative CPU interval unavailable, and window_cpu_s is a
        # required reading of that same interval, so the window has no CPU evidence.
        if cpu is None:
            raise ValueError(f"self_cpu is unavailable ({role['self_cpu']['reason']}); the window has no CPU evidence")
        # One reading, two representations: Go's Duration.Seconds() of the same nanoseconds.
        if type(seconds) not in (int, float) or not math.isclose(seconds, cpu / 1e9, rel_tol=1e-12, abs_tol=1e-9):
            raise ValueError("self_cpu metric does not match window_cpu_s")
    for field in ("peak_rss_at_sample", "peak_rss_end"):
        check_rss(field, server.get(field), platform_profile)
    if platform_profile == LINUX:
        for legacy, field in (("rss_kb_at_20s", "peak_rss_at_sample"), ("rss_kb_end", "peak_rss_end")):
            if server.get(legacy) != server[field]["value"]:
                raise ValueError(f"{legacy}: RSS alias does not match its {field} reading")
    for connection in server["connections"]:
        lost = check_metric("packets_lost_metric", connection.get("packets_lost_metric"), "packets")
        check_source("packets_lost_metric", connection["packets_lost_metric"], platform_profile, "packets_lost_metric")
        if connection.get("controller") != controller:
            raise ValueError("a server connection ran another controller")
        if controller == "reno":
            if lost is None or connection.get("packets_lost") != lost:
                raise ValueError("Reno packets lost must be counted")
        elif lost is not None or "packets_lost" in connection:
            raise ValueError(f"{controller} packets lost has no producer and must stay unavailable")
    delivered = check_metric("useful_bytes", client.get("useful_bytes"), "bytes")
    check_source("useful_bytes", client["useful_bytes"], platform_profile, "useful_bytes")
    if delivered != sum(flow["useful_bytes"] for flow in client["flows"]):
        raise ValueError("useful bytes metric does not match the flows")


def check_observation(record):
    cell, profile = record["cell"], record["profile"]
    server, client = record["server"], record["client"]
    controller = record.get("controller", "reno")
    platform_profile = record.get("platform_profile")
    if platform_profile not in PROFILES:
        raise ValueError(f"{cell}: unknown platform profile {platform_profile}")
    cells = PROFILES[platform_profile]["cells"]
    if cell not in cells:
        raise ValueError(f"{cell}: not in the {platform_profile} inventory")
    if controller not in ("reno", "bbrv3") or any(
            role.get("controller", "reno") != controller for role in (server, client)):
        raise ValueError(f"{cell}: controller does not match both roles")
    check_identity(record, platform_profile)
    check_metrics(record, platform_profile, controller)
    if server["application_send_call_boundary"] != METRIC_BOUNDARIES["application_send_call"]:
        raise ValueError(f"{cell}: application send-call metric boundary mismatch")
    if client["go"] != GO_VERSION:
        raise ValueError(f"{cell}: client toolchain {client['go']}")
    if server["go"] != GO_VERSION:
        raise ValueError(f"{cell}: toolchain {server['go']}")
    if server["granted"] != (profile == OPTED_IN):
        raise ValueError(f"{cell}/{profile}: grant does not match the profile")
    if profile == OPTED_IN and not server["joined"]:
        raise ValueError(f"{cell}: write authority did not join")
    if server["gso_capable"] != (PROFILES[platform_profile]["gso"] and not cells[cell]["env"]):
        raise ValueError(f"{cell}: acceleration does not match the cell")
    if profile not in (CONTROL, OPTED_IN):
        raise ValueError(f"unknown profile {profile}")
    negotiated = PROFILES[platform_profile]["negotiated_multipath"]
    if server.get("multipath_advertised") != (negotiated and profile == OPTED_IN):
        raise ValueError(f"{cell}/{profile}: multipath advertisement does not match the platform profile")
    closes = client["flows"] + server["connections"]
    if profile == CONTROL and (server["write_errors"] or any(
            item["timeout_close"] or item["close_cause"] for item in closes)):
        raise ValueError(f"{cell}: failed control observation is invalid comparator evidence")
    legacy = ("rss_kb_at_20s", "rss_kb_end")
    if platform_profile == LINUX:
        fields = ("window_cpu_s", *legacy)
    else:
        if any(field in server for field in legacy):
            raise ValueError(f"{cell}: native records carry no Linux VmHWM counters")
        if record.get("host_activity", {}).get("status") not in HOST_STATUSES:
            raise ValueError(f"{cell}: host activity must be observed, unavailable or inconclusive")
        fields = ("window_cpu_s",)
    for field in fields:
        if not math.isfinite(server[field]) or server[field] <= 0:
            raise ValueError(f"{cell}: invalid {field}")
    for flow in client["flows"]:
        if len(flow["series"]) != WINDOW_S:
            raise ValueError(f"{cell}: {flow['label']} has {len(flow['series'])} seconds")
        if any(type(value) is not int or value < 0 for value in flow["series"]):
            raise ValueError(f"{cell}: invalid useful-byte series")
        if sum(flow["series"]) != flow["useful_bytes"]:
            raise ValueError(f"{cell}: {flow['label']} useful bytes do not match its series")
    ordinary = flows(record, "ordinary")
    if len(ordinary) != 1:
        raise ValueError(f"{cell}: {len(ordinary)} ordinary flows")
    if not ordinary[0]["control"] or not ordinary[0]["control"]["count"]:
        raise ValueError(f"{cell}: no control samples")
    if not server["application_send_call"].get("ordinary", {}).get("count"):
        raise ValueError(f"{cell}: no application send-call samples")
    for metric in (ordinary[0]["control"], server["application_send_call"]["ordinary"]):
        if not math.isfinite(metric["p99_us"]) or metric["p99_us"] < 0:
            raise ValueError(f"{cell}: invalid latency")
    if ordinary[0]["useful_bytes"] <= 0:
        raise ValueError(f"{cell}: no useful delivery")
    if cell == "mixed-bulk":
        check_mixed(record)
    elif len(client["flows"]) != 1:
        raise ValueError(f"{cell}: unexpected background flow")
    if cell == "stateless-pressure" and not client["flood"]["sent"]:
        raise ValueError(f"{cell}: no pressure applied")


def check_mixed(record):
    background = flows(record, "background")
    if record["profile"] == CONTROL:
        if len(background) != 2:
            raise ValueError("mixed-bulk control needs two independent connections")
        return
    if len(background) != 1 or not background[0].get("multipath_negotiated") or background[0].get("paths") != ["live", "live"]:
        raise ValueError("mixed-bulk opted-in needs one negotiated two-path connection")


def same(actual, expected):
    """Equality that keeps JSON types apart: true is not 1, and 0 is not false."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(same(actual[key], expected[key]) for key in expected)
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(same(a, e) for a, e in zip(actual, expected))
    return actual == expected


LIFECYCLE_STATE_FIELDS = {"wire_id": int, "tuple_generation": int, "lifecycle": str, "local_use": str,
                          "primary": bool, "validated": bool}


def check_path_state(name, state):
    """One recorded StateV1 observation, typed as the producer wrote it."""
    if not isinstance(state, dict) or state.keys() != LIFECYCLE_STATE_FIELDS.keys() or any(
            type(state[field]) is not kind for field, kind in LIFECYCLE_STATE_FIELDS.items()):
        raise ValueError(f"{name}: malformed path state {state}")
    if not 0 <= state["wire_id"] < PATH_ID_LIMIT or not 0 <= state["tuple_generation"] < 2**64:
        raise ValueError(f"{name}: path state outside the producer's uint32/uint64 range")


def lifecycle_phase_admits(phase, path_id, state, retired):
    """The sampled path's observed state is the phase; mirrors ordinaryCostPhaseAdmits."""
    if (type(path_id) is not int or not 0 <= path_id < PATH_ID_LIMIT
            or not isinstance(state, dict) or type(state.get("wire_id")) is not int or state["wire_id"] != path_id):
        raise ValueError(f"{phase}: the observation is not of the sampled path {path_id}")
    lifecycle = state.get("lifecycle")
    if phase == "negotiated-idle":
        if (path_id != 0 or lifecycle != "live" or state.get("validated") is not True
                or state.get("primary") is not True or state.get("local_use") != "active"):
            raise ValueError(f"{phase} needs live, validated, primary path zero, not {state}")
    elif phase == "validated-backup":
        if (path_id == 0 or lifecycle != "live" or state.get("validated") is not True
                or state.get("primary") is not False or state.get("local_use") != "backup"):
            raise ValueError(f"{phase} needs a live, validated backup path besides path zero, not {state}")
    elif phase == "retired":
        # A live path is not retired, even after a same-ID migration detached its old
        # transport, and a requested abandonment is not observed retirement.
        if path_id == 0 or lifecycle != retired:
            raise ValueError(f"{phase} needs the backup path {retired}, not path {path_id} {lifecycle}")
    else:
        raise ValueError(f"unknown lifecycle phase {phase}")


def check_lifecycle(record):
    """One negotiated lifecycle-memory record from the two public-admission roles."""
    platform_profile = record.get("platform_profile")
    if platform_profile not in PROFILES:
        raise ValueError(f"unknown platform profile {platform_profile}")
    if record.get("workload") != LIFECYCLE:
        raise ValueError("not a lifecycle-memory record")
    controller, retired = record.get("controller"), record.get("retired_lifecycle")
    if controller not in ("reno", "bbrv3"):
        raise ValueError(f"unknown lifecycle controller {controller}")
    if retired not in LIFECYCLE_RETIRED:
        raise ValueError(f"the qualifying retirement state is retained or closed, not {retired}")
    check_identity(record, platform_profile)
    server, client = record["server"], record["client"]
    if not same(record.get("exit"), {"server": 0, "client": 0}):
        raise ValueError(f"both roles must exit 0, not {record.get('exit')}")
    for role, result in (("server", server), ("client", client)):
        if result.get("format") != LIFECYCLE_FORMAT:
            raise ValueError(f"{role}: unsupported lifecycle record format {result.get('format')}")
        if result.get("role") != role or result.get("controller") != controller or result.get("go") != GO_VERSION:
            raise ValueError(f"{role}: role, controller or toolchain does not match the run")
        if result.get("multipath_negotiated") is not True:
            raise ValueError(f"{role}: an unnegotiated connection is no lifecycle or backup control")
        if result.get("grant_join_source") != LIFECYCLE_BOUNDARY_SOURCES["grant_joins"]:
            raise ValueError(f"{role}: grant joins come from WaitMultipathIOStoppedV1")
    if not same(server.get("grant_joins"), {"origin": True}):
        raise ValueError("server: its grant did not join")
    if server.get("peer_closed") is not True:
        raise ValueError(f"server: the connection ended without the client's close: {server.get('close_cause')}")
    if client.get("retired_lifecycle") != retired:
        raise ValueError("client: its qualifying retirement state is not the run's")
    if not same(client.get("grant_joins"), {"origin": True, "backup": True}):
        raise ValueError("client: every grant must join, separately from detachment")
    if not same(client.get("transport_detachment"), {"transport": "backup", "detached": True,
                                                     "source": LIFECYCLE_BOUNDARY_SOURCES["transport_detachment"]}):
        raise ValueError("client: the retired path's transport did not detach")
    samples = client.get("samples")
    if not isinstance(samples, list) or tuple(sample.get("phase") for sample in samples) != LIFECYCLE_PHASES:
        raise ValueError(f"samples must be exactly {LIFECYCLE_PHASES} in order")
    for sample in samples:
        phase = sample["phase"]
        if sample.get("role") != "client":
            raise ValueError(f"{phase}: sampled by {sample.get('role')}, not the client role")
        if sample.get("multipath_negotiated") is not True:
            raise ValueError(f"{phase}: an unnegotiated connection is no lifecycle or backup control")
        expected = None if phase == "negotiated-idle" else "negotiated-idle"
        if sample.get("baseline", "missing") != expected:
            raise ValueError(f"{phase}: its matched comparison is {expected}, not {sample.get('baseline', 'missing')}")
        path_id = sample.get("path_id")
        if type(path_id) is not int or not 0 <= path_id < PATH_ID_LIMIT:
            raise ValueError(f"{phase}: no uint32 sampled path ID")
        for field in ("state_before", "state_after"):
            check_path_state(f"{phase} {field}", sample.get(field))
        if not same(sample["state_before"], sample["state_after"]):
            raise ValueError(f"{phase}: stale sample; the path left the phase during the reading")
        lifecycle_phase_admits(phase, path_id, sample.get("state_before"), retired)
        heap = check_metric(f"{phase} go_heap_live", sample.get("go_heap_live"), "bytes")
        if heap is None or sample["go_heap_live"]["source"] != LIFECYCLE_BOUNDARY_SOURCES["go_heap_live"]:
            raise ValueError(f"{phase}: no live Go-heap reading")
        check_rss(f"{phase} peak_rss", sample.get("peak_rss"), platform_profile)
    if samples[1]["path_id"] != samples[2]["path_id"]:
        raise ValueError("retirement must sample the backup's path ID")


def match_lifecycle(first, second):
    """Two valid lifecycle records that one comparison may pair: one qualifying retirement
    state on both sides, with the same phase, role and path labels. Returns per-phase heap
    pairs. Which records a comparison pairs, and how it judges them, is Q1's protocol."""
    for record in (first, second):
        # Only a completed attempt is evidence; a failed one can still carry its payloads.
        if record.get("status") != "succeeded":
            raise ValueError(f"a comparison pairs succeeded attempts, not {record.get('status')}")
        check_lifecycle(record)
    if first["retired_lifecycle"] != second["retired_lifecycle"]:
        raise ValueError(f"one side retired to {first['retired_lifecycle']}, the other to {second['retired_lifecycle']}")
    pairs = {}
    for a, b in zip(first["client"]["samples"], second["client"]["samples"]):
        if (a["phase"], a["role"], a["path_id"]) != (b["phase"], b["role"], b["path_id"]):
            raise ValueError(f"{a['phase']}: the two sides sampled different roles or paths")
        pairs[a["phase"]] = (a["go_heap_live"]["value"], b["go_heap_live"]["value"])
    return pairs


def check_accounting(records, cells=None):
    if any(record.get("mode") != "campaign" or record.get("cpu_profile", False)
           or record.get("controller", "reno") != "reno" or record.get("platform_profile") != LINUX
           for record in records):
        raise ValueError("diagnostic/smoke, profiled, BBR or native records cannot satisfy the Reno campaign inventory")
    expected = sorted(schedule(cells))
    actual = sorted((record["cell"], record["round"], record["profile"], record["seed"]) for record in records)
    if actual != expected:
        raise ValueError(f"{len(actual)} instances do not match the {len(expected)} scheduled")
    for record in records:
        check_observation(record)


def spread(values):
    return {"median": statistics.median(values), "range": [min(values), max(values)], "rounds": values}


def useful_bytes(record):
    return sum(flow["useful_bytes"] for flow in record["client"]["flows"])


def latency_margin(base, treated):
    """Microseconds above the limit: the larger of 110% of baseline or baseline plus 1 ms."""
    return treated - max(LATENCY_FACTOR * base, base + LATENCY_ALLOWANCE_US)


def workload_failures(record):
    """Execution failures of either arm, which decide an unjudged smoke. A flow that
    delivered nothing is a valid record (the Reno thresholds judge its fair progress), but
    an unjudged smoke cannot pass on it."""
    failures = []
    if record["server"]["write_errors"]:
        failures.append(f"{record['profile']}: {record['server']['write_errors']} write errors")
    # Each cell's demanded effect: every flow delivers, and offered pressure draws resets.
    for flow in record["client"]["flows"]:
        if flow["useful_bytes"] <= 0:
            failures.append(f"{record['profile']}: {flow['label']} delivered no useful bytes")
    flood = record["client"].get("flood")
    if flood and flood["sent"] and not flood["resets"]:
        failures.append(f"{record['profile']}: {flood['sent']} pressure packets drew no stateless reset")
    for item in record["client"]["flows"] + record["server"]["connections"]:
        if item["timeout_close"] or item["close_cause"]:
            failures.append(f"{record['profile']}: {item['label']} closed: {item['close_cause'] or 'timeout'}")
    return failures


def memory_readings(record, platform_profile=LINUX):
    """The server's peak RSS at the sample point and at the end, in the unit the memory rule
    compares: Linux keeps R18's VmHWM kB aliases; Darwin reads normalized bytes."""
    server = record["server"]
    if platform_profile == LINUX:
        return server["rss_kb_at_20s"], server["rss_kb_end"]
    return server["peak_rss_at_sample"]["bytes"], server["peak_rss_end"]["bytes"]


def judge_cell(cell, rounds, platform_profile=LINUX, round_numbers=None):
    """Judge one cell from its (control, opted-in) rounds, on medians of paired values.
    Failures name rounds by round_numbers when given (the protocol's N), else by index."""
    labels = list(round_numbers) if round_numbers is not None else list(range(len(rounds)))
    goodput, cpu, control_margin, send_margin = [], [], [], []
    control_p99, send_p99 = {CONTROL: [], OPTED_IN: []}, {CONTROL: [], OPTED_IN: []}
    empty = {CONTROL: [], OPTED_IN: []}
    background = {CONTROL: [], OPTED_IN: []}
    resets = {CONTROL: [], OPTED_IN: []}
    offered = {CONTROL: [], OPTED_IN: []}
    returned = {CONTROL: [], OPTED_IN: []}
    peak = {CONTROL: [], OPTED_IN: []}
    lost = {CONTROL: [], OPTED_IN: []}
    drops = {CONTROL: [], OPTED_IN: []}
    write_errors = {CONTROL: [], OPTED_IN: []}
    timeouts, failed_sends, unbounded, starved = [], [], [], []
    for round_, (base, treated) in enumerate(rounds):
        base_flow, treated_flow = flows(base, "ordinary")[0], flows(treated, "ordinary")[0]
        goodput.append(treated_flow["useful_bytes"] / base_flow["useful_bytes"])
        cpu.append((treated["server"]["window_cpu_s"] / useful_bytes(treated)) / (base["server"]["window_cpu_s"] / useful_bytes(base)))
        base_control = base_flow["control"]["p99_us"]
        treated_control = treated_flow["control"]["p99_us"]
        control_margin.append(latency_margin(base_control, treated_control))
        base_send = base["server"]["application_send_call"]["ordinary"]["p99_us"]
        treated_send = treated["server"]["application_send_call"]["ordinary"]["p99_us"]
        send_margin.append(latency_margin(base_send, treated_send))
        for name, record in ((CONTROL, base), (OPTED_IN, treated)):
            flow = flows(record, "ordinary")[0]
            control_p99[name].append(flow["control"]["p99_us"])
            send_p99[name].append(record["server"]["application_send_call"]["ordinary"]["p99_us"])
            empty[name].append(sum(1 for value in flow["series"] if value == 0))
            background[name].append(sum(f["useful_bytes"] for f in flows(record, "background")))
            peak[name].append(memory_readings(record, platform_profile)[1])
            counted = [c["packets_lost_metric"]["value"] for c in record["server"]["connections"]]
            lost[name].append(None if None in counted else sum(counted))
            drops[name].append(sum(f.get("datagram_drops", 0) for f in record["client"]["flows"]))
            write_errors[name].append(record["server"]["write_errors"])
            flood = record["client"].get("flood")
            offered[name].append(flood["sent"] if flood else 0)
            returned[name].append(flood["resets"] if flood else 0)
            if flood and flood["sent"]:
                resets[name].append(flood["resets"] / flood["sent"])
        closes = treated["client"]["flows"] + treated["server"]["connections"]
        if any(item["timeout_close"] for item in closes):
            timeouts.append(labels[round_])
        if treated["server"]["write_errors"] or any(item["close_cause"] and not item["timeout_close"] for item in closes):
            failed_sends.append(labels[round_])
        at_sample, end = memory_readings(treated, platform_profile)
        if end > MEMORY_GROWTH_CEILING * at_sample:
            unbounded.append(labels[round_])
        if any(value == 0 for flow in treated["client"]["flows"] for value in flow["series"]):
            starved.append(labels[round_])
    failures = []
    if statistics.median(goodput) < GOODPUT_FLOOR:
        failures.append(f"goodput ratio {statistics.median(goodput):.3f} below {GOODPUT_FLOOR}")
    if statistics.median(cpu) > CPU_CEILING:
        failures.append(f"CPU per useful byte ratio {statistics.median(cpu):.3f} above {CPU_CEILING}")
    if statistics.median(control_margin) > 0:
        failures.append(f"control p99 {statistics.median(control_margin):.0f} us over its limit")
    if statistics.median(send_margin) > 0:
        failures.append(f"application send-call p99 {statistics.median(send_margin):.0f} us over its limit")
    if timeouts:
        failures.append(f"timeout-only close in rounds {timeouts}")
    if failed_sends:
        failures.append(f"write error or non-timeout close in rounds {failed_sends}")
    if unbounded:
        failures.append(f"memory kept growing in rounds {unbounded}")
    if starved:
        failures.append(f"fair progress: an empty second in rounds {starved}")
    return {
        "cell": cell,
        "passed": not failures,
        "failures": failures,
        "goodput_ratio": spread(goodput),
        "cpu_per_useful_byte_ratio": spread(cpu),
        "control_p99_margin_us": spread(control_margin),
        "application_send_call_p99_margin_us": spread(send_margin),
        "control_p99_us": control_p99,
        "application_send_call_p99_us": send_p99,
        "empty_seconds": empty,
        "background_bytes": background,
        "stateless_reset_share": resets,
        "stateless_offered_packets": offered,
        "stateless_resets_received": returned,
        ("peak_rss_kb" if platform_profile == LINUX else "peak_rss_bytes"): peak,
        "packets_lost": lost,
        "datagram_drops": drops,
        "write_errors": write_errors,
    }


def summarize(records, cells=None):
    check_accounting(records, cells)
    keyed = {(record["cell"], record["round"], record["profile"]): record for record in records}
    verdicts = {}
    for cell in schedule_cells(cells):
        rounds = [(keyed[(cell, round_, CONTROL)], keyed[(cell, round_, OPTED_IN)]) for round_ in range(ROUNDS)]
        verdicts[cell] = judge_cell(cell, rounds)
    failed = [cell for cell, verdict in verdicts.items() if not verdict["passed"]]
    contaminated = sum(1 for record in records if record["contaminated"])
    return {
        "passed": not failed and not contaminated,
        "failed_cells": failed,
        "cells": verdicts,
        "contaminated_observations": contaminated,
    }


def foreign_limit_s(duration_s):
    return FOREIGN_SHARE_LIMIT * duration_s


def rerun_due(pair, attempt, reruns_used):
    """One recorded rerun of a contaminated pair. The rule never sees a result."""
    return attempt == 0 and reruns_used < MAX_RERUN_PAIRS and any(record["contaminated"] for record in pair)


def schedstat_running_ns():
    running = {}
    for line in Path("/proc/schedstat").read_text().splitlines():
        if line.startswith("cpu"):
            parts = line.split()
            running[int(parts[0][3:])] = int(parts[7])
    return running


def softirqd_ns():
    ticks = 0
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
        except OSError:
            continue
        name = stat[stat.index("(") + 1:stat.rindex(")")]
        if name.startswith("ksoftirqd/") and int(name.split("/")[1]) in FIXTURE_CPUS:
            fields = stat[stat.rindex(")") + 2:].split()
            ticks += int(fields[11]) + int(fields[12])
    return ticks * 1e9 / os.sysconf("SC_CLK_TCK")


def fixture_busy_share(sample_s=2.0):
    before = schedstat_running_ns()
    time.sleep(sample_s)
    after = schedstat_running_ns()
    return max((after[cpu] - before[cpu]) / (sample_s * 1e9) for cpu in FIXTURE_CPUS)


def wait_quiet(log):
    waited = 0.0
    while True:
        busy = subprocess.run(["pgrep", "-f", HOST_BUSY_PATTERN], capture_output=True, check=False).returncode == 0
        share = fixture_busy_share()
        # Background processes on other cores do not contaminate the fixture.
        if share < QUIET_BUSY_SHARE:
            return {"waited_s": waited, "fixture_busy_share": share, "named_process_present": busy}
        log(f"host busy: named process {busy}, fixture share {share:.3f}")
        time.sleep(13)
        waited += 15
        if waited > QUIET_WAIT_LIMIT_S:
            raise RuntimeError(f"host stayed busy for {waited:.0f} s")


class HostObservationError(ValueError):
    """A host observation that cannot attribute activity: unavailable or inconclusive."""

    def __init__(self, status, reason):
        super().__init__(reason)
        self.status = status


CLUSTER_NAME = re.compile(r"^(?P<kind>[EP])\d*-Cluster$")
CLUSTER_CLASS = {"E": "efficiency", "P": "performance"}


def parse_powermetrics(raw):
    """powermetrics --format plist writes NUL-separated plist records; plistlib owns their
    syntax. A malformed record fails. Only a final record cut off by stopping the sampler
    is set aside, as tail bytes that are not evidence. Returns (records, tail bytes)."""
    chunks = raw.split(b"\0")
    records, tail = [], 0
    for index, chunk in enumerate(chunks):
        if not chunk.strip():
            continue
        try:
            record = plistlib.loads(chunk.strip(), fmt=plistlib.FMT_XML)
        except Exception as error:
            if index == len(chunks) - 1:
                tail = len(chunk)
                continue
            raise ValueError(f"malformed powermetrics plist record {index}: {error}") from error
        if not isinstance(record, dict):
            raise ValueError(f"powermetrics plist record {index} is not a dictionary")
        records.append(record)
    return records, tail


def delta_records(records):
    """The adapter's per-record rules, shared with the X3 capture reader: every record is a
    positive delta sample (is_delta true, a positive integer elapsed_ns) whose processor
    clusters carry E/P names, supported idle and down residency and no repeated name, and
    every record has the same cluster set. Returns the cluster names, each record's
    elapsed_ns and each cluster's elapsed-weighted active time; anything else is
    inconclusive."""
    names, active, elapsed_ns = None, {}, []
    for index, record in enumerate(records):
        elapsed = record.get("elapsed_ns")
        if record.get("is_delta") is not True or type(elapsed) is not int or elapsed <= 0:
            raise HostObservationError("inconclusive", f"record {index} is not a positive delta sample")
        clusters = record.get("processor", {}).get("clusters") if isinstance(record.get("processor"), dict) else None
        if not isinstance(clusters, list) or not clusters:
            raise HostObservationError("inconclusive", f"record {index} has no processor clusters")
        seen = []
        for cluster in clusters:
            name = cluster.get("name") if isinstance(cluster, dict) else None
            if not isinstance(name, str) or not CLUSTER_NAME.match(name):
                raise HostObservationError("inconclusive", f"unsupported cluster name {name!r}")
            if name in seen:
                raise HostObservationError("inconclusive", f"record {index} repeated cluster {name}")
            shares = [cluster.get(field) for field in ("idle_ratio", "down_ratio")]
            if any(type(share) not in (int, float) or not math.isfinite(share) or not 0 <= share <= 1
                   for share in shares) or sum(shares) > 1 + 1e-9:
                raise HostObservationError("inconclusive", f"{name}: unsupported idle/down residency {shares!r}")
            seen.append(name)
            active[name] = active.get(name, 0.0) + elapsed * max(0.0, 1 - sum(shares))
        if names is not None and seen != names:
            raise HostObservationError("inconclusive", f"record {index} changed the cluster set")
        names = seen
        elapsed_ns.append(elapsed)
    return names or [], elapsed_ns, active


def cluster_activity(records, coverage):
    """Elapsed-weighted active residency (1 - idle_ratio - down_ratio) of each CPU cluster,
    labeled by the producer's E/P cluster name, averaged over the sampler's lifetime.

    coverage holds the driver's monotonic times: the window, a launch read before the
    sampler could exist, and a stop read after it was reaped. Delta samples are contiguous
    (each covers the time since the previous one) from some unknown start delay after
    launch, and they finish before the stop, so they certainly cover the window only when
    their total elapsed time reaches the window's end from launch and reaches back to its
    start from the stop. Second-resolution timestamps are not used. Unsupported fields or
    uncertain coverage are inconclusive."""
    if not records:
        raise HostObservationError("inconclusive", "no complete powermetrics record")
    names, elapsed_ns, active = delta_records(records)
    elapsed_total = sum(elapsed_ns)
    total_s = elapsed_total / 1e9
    lifetime_s = coverage["stopped"] - coverage["launched"]
    if total_s > lifetime_s + SAMPLER_SLACK_S:
        raise HostObservationError("inconclusive", f"records claim {total_s:.3f} s of a {lifetime_s:.3f} s sampler lifetime")
    if coverage["launched"] + total_s < coverage["window_end"] or coverage["stopped"] - total_s > coverage["window_start"]:
        raise HostObservationError("inconclusive",
                                   f"{total_s:.3f} s of samples cannot be placed over the whole window")
    return {
        "status": "observed",
        "scope": "sampler lifetime, which brackets the window",
        "records": len(records),
        "elapsed_ns": elapsed_total,
        "clusters": [{"name": name, "class": CLUSTER_CLASS[CLUSTER_NAME.match(name)["kind"]],
                      "active_ratio": active[name] / elapsed_total} for name in names],
    }


def powermetrics_command(mode="driver-stopped"):
    """The sampler route D6 A authorizes: the owner-installed wrapper, which runs exactly one
    of the protocol's two powermetrics argument lists (powermetrics_wrapper.py). sudo -n
    never prompts, so a missing grant fails at once and is recorded unavailable. The
    driver-stopped mode stops when its standard input closes; bounded is X3's capture."""
    return [SUDO, "-n", SAMPLER_WRAPPER, mode]


def launch_sampler(command, stdout, stderr):
    """Launch the sampler with a pipe as its standard input. The pipe's write end is the
    driver's only handle on it: Popen makes that end non-inheritable, so roles launched
    later never hold it, and the driver's exit, even by SIGKILL, closes it and stops the
    sampler. Its own session has no controlling terminal, so sudo cannot place a terminal
    between the pipe and the wrapper, and terminal interrupts reach only the driver."""
    return subprocess.Popen(command, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr, start_new_session=True)


def stop_sampler(process, timeout):
    """Close the sampler's standard input, then wait up to timeout for it to exit. Never
    signals it: under sudo it runs as root. Returns whether it was reaped."""
    process.stdin.close()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    return True


class DeferredInterrupts:
    """SIGINT and SIGTERM during one observation. They raise only inside an interruptible
    wait; anywhere else (child launch and registration, teardown, sampler stop and
    attribution) they are recorded and honored once teardown ends: every role reaped and
    the sampler reaped or left unconfirmed after its bounded stop. The handler disarms
    before raising, so a second signal cannot interrupt the cleanup the first began.
    Children keep the caller's delivery: nothing is masked, exec resets the handler to the
    default, and an inherited ignore stays installed, so children inherit it too."""

    SIGNALS = (signal.SIGINT, signal.SIGTERM)

    def __enter__(self):
        # All state exists before the first handler can run.
        self.pending, self.armed, self.installed = [], False, []
        self.previous = {number: signal.getsignal(number) for number in self.SIGNALS}
        try:
            for number in self.SIGNALS:
                if self.previous[number] is not signal.SIG_IGN:
                    signal.signal(number, self.handle)
                    self.installed.append(number)
        except BaseException:
            self.restore()
            raise
        return self

    def restore(self):
        for number in self.installed:
            previous = self.previous[number]
            signal.signal(number, signal.SIG_DFL if previous is None else previous)
        self.installed = []

    def handle(self, number, frame):
        self.pending.append(number)
        if self.armed:
            self.armed = False
            raise KeyboardInterrupt(signal.Signals(number).name)

    @contextlib.contextmanager
    def interruptible(self):
        self.armed = True  # armed first: a signal after this raises; one before is pending
        try:
            if self.pending:
                self.armed = False
                raise KeyboardInterrupt(signal.Signals(self.pending[0]).name)
            yield
        finally:
            self.armed = False

    def __exit__(self, kind, error, traceback):
        self.restore()
        if error is None and self.pending:
            number = self.pending[0]
            handler = self.previous[number]
            if callable(handler):
                handler(number, None)  # the caller's handler, such as main's SIGTERM conversion
            raise KeyboardInterrupt(signal.Signals(number).name)
        return False


def window_bounds(start_at_unix_ns, warmup_s, window_s, monotonic=time.monotonic, wall_ns=time.time_ns):
    """The roles' wall-clock window on this process's monotonic clock. The wall-clock read
    is bracketed by monotonic reads, so the window starts no earlier than the first bound
    and ends no later than the second, whatever preemption separated the reads."""
    before = monotonic()
    wall = wall_ns()
    after = monotonic()
    offset = (start_at_unix_ns - wall) / 1e9 + warmup_s
    return before + offset, after + offset + window_s


class HostSampler:
    """One optional host sampler bracketing an observation. It is stopped by closing its
    standard input and joined within a bound, and its raw output is kept as host.plist. A
    sampler not joined within the bound may still be writing host.plist, so its record
    describes a snapshot of the bytes read, kept beside the live file."""

    def __init__(self, command, directory):
        self.command, self.directory = command, directory
        self.raw_path, self.log_path = directory / "host.plist", directory / "host.log"
        self.snapshot_path = directory / "host.snapshot.plist"
        self.process, self.started, self.launch_error = None, None, None
        self.halted, self.reaped = None, None

    def start(self):
        """A sampler that cannot launch leaves the observation running, unattributed. The
        launch is read first, so no sample can predate it."""
        self.started = time.monotonic()
        try:
            with self.raw_path.open("wb") as raw, self.log_path.open("wb") as log:
                self.process = launch_sampler(self.command, stdout=raw, stderr=log)
        except OSError as error:
            self.launch_error = f"{type(error).__name__}: {error}"

    def stop(self):
        """Close standard input and wait for the sampler, bounded by SAMPLER_STOP_S; returns
        whether it exited before being stopped. SIGINT and SIGTERM stay blocked for this
        bounded section, so an operator interrupt is delivered after the bounded wait ends,
        whether or not it reaped the sampler, rather than between its steps. Standard input
        closes first, so even a failed wait leaves the sampler stopping on its own."""
        if self.process is None:
            return False
        interrupts = {signal.SIGINT, signal.SIGTERM}
        blocked = signal.pthread_sigmask(signal.SIG_BLOCK, interrupts)
        try:
            early = self.process.poll() is not None  # poll reaps an exited sampler
            self.reaped = stop_sampler(self.process, SAMPLER_STOP_S)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
        return early

    def halt(self):
        """Stop the sampler once, within the bound, recording the stop request time and the
        time the wait ended."""
        if self.halted is None:
            requested = time.monotonic()
            early = self.stop()
            # Read after the wait: only when it reaped the sampler does no sample postdate it.
            self.halted = (requested, early, time.monotonic())
        return self.halted

    def finish(self, window_start, window_end):
        """Stop the sampler if it is still running and attribute what it recorded, for
        conservative monotonic window bounds (the earliest start and the latest end)."""
        requested, early, stopped_at = self.halt()
        raw = self.raw_path.read_bytes() if self.raw_path.exists() else b""
        unconfirmed = self.process is not None and not self.reaped
        retained = self.raw_path
        if unconfirmed:
            # The sampler may still hold host.plist as its stdout, so the digest describes a
            # snapshot of exactly these bytes. The live file is never replaced or renamed.
            retained = self.snapshot_path
            with retained.open("xb") as snapshot:
                snapshot.write(raw)
        result = {"command": self.command, "exit": self.process.returncode if self.process else None,
                  "joined": self.process is not None and self.process.returncode is not None,
                  "raw_path": str(retained), "raw_bytes": len(raw),
                  "raw_sha256": hashlib.sha256(raw).hexdigest()}
        if unconfirmed:
            result.update(live_raw_path=str(self.raw_path),
                          live_raw_note="the unconfirmed sampler may still hold this file as its stdout "
                                        "and append to it, so it may still grow past the snapshot")
        try:
            if self.process is None:
                raise HostObservationError("unavailable", f"sampler never launched: {self.launch_error}")
            if not self.reaped:
                raise HostObservationError("unavailable", f"sampler not confirmed stopped within {SAMPLER_STOP_S} s "
                                                          "after its stdin closed; it was not signaled")
            log = self.log_path.read_text(errors="replace").strip()[-500:]
            if early and self.process.returncode != 0:
                raise HostObservationError("unavailable", f"sampler exited {self.process.returncode}: {log}")
            if self.started > window_start:
                raise HostObservationError("inconclusive", "sampler started after the window began")
            if early or requested < window_end:
                raise HostObservationError("inconclusive", "sampler ended before the window ended")
            records, tail = parse_powermetrics(raw)
            coverage = {"launched": self.started, "stopped": stopped_at,
                        "window_start": window_start, "window_end": window_end}
            result.update(cluster_activity(records, coverage), tail_bytes=tail)
        except HostObservationError as error:
            result.update(status=error.status, reason=str(error))
        except ValueError as error:
            result.update(status="inconclusive", reason=str(error))
        return result


def role_command(binary, cpu_profile=None, test="TestOrdinaryCostRole", timeout_s=SETUP_S + WARMUP_S + WINDOW_S + 60):
    command = [binary, f"-test.run=^{test}$", "-test.count=1", "-test.v", f"-test.timeout={timeout_s}s"]
    if cpu_profile is not None:
        command.append(f"-test.cpuprofile={cpu_profile}")
    return command


def check_role_log(role, output, test="TestOrdinaryCostRole"):
    if output.count(f"--- PASS: {test} ") != 1:
        raise ValueError(f"{role} must pass exactly once:\n{output[-2000:]}")


def run_observation(binary, directory, cell, round_, profile, seed, warmup_s=WARMUP_S,
                    window_s=WINDOW_S, timeout_s=135, record=None, controller="reno", cpu_profile=False,
                    platform_profile=LINUX, host_sampler=False):
    """One instance; every launched role is reaped, even after a partial launch, and a host
    sampler is reaped or, if its bounded stop is not confirmed, left running unsignaled and
    recorded unavailable. Linux pins the roles and attributes foreign CPU; the native profile
    reports optional host activity instead, and never judges the host quiet."""
    record = record if record is not None else {}
    linux = platform_profile == LINUX
    directory.mkdir(parents=True, exist_ok=False)
    spec = {
        "cell": cell, "profile": profile, "seed": seed, "address": SERVER_ADDRESS, "controller": controller,
        "start_at_unix_ns": time.time_ns() + SETUP_S * 10**9,
        "warmup_ns": warmup_s * 10**9, "window_ns": window_s * 10**9,
    }
    env = {key: value for key, value in os.environ.items() if not key.startswith("QUIC_GO_")}
    env["GOMAXPROCS"] = "4"
    processes, usage = {}, {}
    before = schedstat_running_ns() if linux else None
    softirq_before = softirqd_ns() if linux else None
    begun = time.monotonic()
    deadline = begun + timeout_s
    # The window in this process's monotonic clock, for the sampler's coverage.
    window = window_bounds(spec["start_at_unix_ns"], warmup_s, window_s)
    sampler = HostSampler(powermetrics_command(), directory) if host_sampler else None
    host = {"status": "unavailable", "reason": "no host sampler selected; Q1 selects and authorizes one"}

    def reap(role, process, timeout=None):
        # Only this script reaps children: the RUSAGE_CHILDREN delta belongs to this role.
        previous = resource.getrusage(resource.RUSAGE_CHILDREN)
        try:
            process.wait(timeout=timeout)
        finally:
            current = resource.getrusage(resource.RUSAGE_CHILDREN)
            usage[role] = usage.get(role, 0) + (current.ru_utime + current.ru_stime
                                               - previous.ru_utime - previous.ru_stime)

    with DeferredInterrupts() as interrupts:
        try:
            if sampler:
                sampler.start()
            for role, cpus, process_env in (("server", SERVER_CPUS, dict(env, **PROFILES[platform_profile]["cells"][cell]["env"])),
                                            ("client", CLIENT_CPUS, env)):
                role_spec = dict(spec, role=role, output=str(directory / f"{role}.json"))
                command = role_command(binary, directory / f"{role}.cpu.pprof" if cpu_profile else None)
                with (directory / f"{role}.log").open("w") as log:
                    processes[role] = subprocess.Popen(
                        ["taskset", "-c", cpus, *command] if linux else command,
                        env=dict(process_env, ORDINARY_COST_SPEC=json.dumps(role_spec)),
                        stdout=log, stderr=subprocess.STDOUT,
                    )
            for role, process in processes.items():
                with interrupts.interruptible():  # the only point an operator interrupt raises
                    reap(role, process, timeout=max(0, deadline - time.monotonic()))
                if process.returncode != 0:
                    raise ValueError(f"{cell}/{profile} {role} exit {process.returncode}")
        finally:
            # Not interruptible: terminate both roles before waiting on either, keep their
            # facts, then stop the sampler. No failed launch or interrupt leaves a role alive;
            # only a sampler not confirmed stopped is left running, unsignaled.
            try:
                for process in processes.values():
                    if process.returncode is None:
                        process.kill()
                for role, process in processes.items():
                    if process.returncode is None:
                        reap(role, process)
            finally:
                record.update(cell=cell, round=round_, profile=profile, seed=seed, controller=controller,
                              platform_profile=platform_profile, cpu_profile=cpu_profile,
                              timing_eligible=not cpu_profile, process_cpu_s=usage,
                              exit={role: process.returncode for role, process in processes.items()})
                try:
                    if sampler:
                        sampler.halt()
                finally:
                    occupied = time.monotonic() - begun
                    record["occupied_s"] = occupied
    # Every role is reaped and the sampler is reaped or recorded unconfirmed: parsing the
    # capture is ordinary, cancellable work.
    if sampler:
        host = sampler.finish(*window)
    if linux:
        running = schedstat_running_ns()
        foreign = (sum(running[cpu] - before[cpu] for cpu in FIXTURE_CPUS)
                   - (softirqd_ns() - softirq_before)) / 1e9 - sum(usage.values())
        record.update(foreign_cpu_s=foreign, contaminated=foreign > foreign_limit_s(occupied))
    else:
        record["host_activity"] = host
    for role in processes:
        check_role_log(role, (directory / f"{role}.log").read_text())
        def reject_nonfinite(value):
            raise ValueError(f"{role}: nonfinite JSON number {value}")
        record[role] = json.loads((directory / f"{role}.json").read_text(), parse_constant=reject_nonfinite)
    check_observation(record)
    if cpu_profile:
        paths = {role: directory / f"{role}.cpu.pprof" for role in processes}
        if any(not path.is_file() or path.stat().st_size == 0 for path in paths.values()):
            raise ValueError("missing CPU profile")
        record["cpu_profiles"] = {role: str(path) for role, path in paths.items()}
    return record


def run_lifecycle(binary, directory, controller, retired, timeout_s, record, platform_profile=LINUX):
    """One negotiated lifecycle-memory observation: an unsampled server role and the
    sampled client role, each its own process. Every launched role is reaped, even after a
    partial launch, before either record is read."""
    directory.mkdir(parents=True, exist_ok=False)
    test = "TestOrdinaryCostLifecycleRole"
    # The roles stop on their own before the driver's deadline would kill them.
    spec = {"controller": controller, "address": SERVER_ADDRESS, "retired_lifecycle": retired,
            "timeout_ns": int(max(1, timeout_s - 10) * 10**9)}
    env = {key: value for key, value in os.environ.items() if not key.startswith("QUIC_GO_")}
    env["GOMAXPROCS"] = "4"
    processes = {}
    begun = time.monotonic()
    deadline = begun + timeout_s
    with DeferredInterrupts() as interrupts:
        try:
            # The client's handshake retransmits until the server listens, so no readiness
            # message is needed; the server goes first all the same.
            for role, cpus in (("server", SERVER_CPUS), ("client", CLIENT_CPUS)):
                role_spec = dict(spec, role=role, output=str(directory / f"{role}.json"))
                command = role_command(binary, test=test, timeout_s=int(timeout_s))
                with (directory / f"{role}.log").open("w") as log:
                    processes[role] = subprocess.Popen(
                        ["taskset", "-c", cpus, *command] if platform_profile == LINUX else command,
                        env=dict(env, ORDINARY_COST_LIFECYCLE_SPEC=json.dumps(role_spec)),
                        stdout=log, stderr=subprocess.STDOUT,
                    )
            for role in ("client", "server"):
                with interrupts.interruptible():
                    processes[role].wait(timeout=max(0, deadline - time.monotonic()))
                if processes[role].returncode != 0:
                    raise ValueError(f"lifecycle {role} exit {processes[role].returncode}")
        finally:
            for process in processes.values():
                if process.returncode is None:
                    process.kill()
            for process in processes.values():
                if process.returncode is None:
                    process.wait()
            record.update(workload=LIFECYCLE, controller=controller, platform_profile=platform_profile,
                          retired_lifecycle=retired, occupied_s=time.monotonic() - begun,
                          exit={role: process.returncode for role, process in processes.items()})
    for role in processes:
        check_role_log(role, (directory / f"{role}.log").read_text(), test)
        def reject_nonfinite(value):
            raise ValueError(f"{role}: nonfinite JSON number {value}")
        record[role] = json.loads((directory / f"{role}.json").read_text(), parse_constant=reject_nonfinite)
    check_lifecycle(record)
    return record


class AttemptLedger:
    """The single owner of supplied capacity and durable, pre-launch attempt charges."""

    def __init__(self, output, remaining_instances, remaining_host_seconds, timeout_s):
        if (remaining_instances < 0 or not math.isfinite(remaining_host_seconds)
                or remaining_host_seconds < 0 or not math.isfinite(timeout_s) or timeout_s <= 0):
            raise ValueError("invalid remaining allowance or timeout")
        self.path = output / "ledger.json"
        self.remaining_instances = remaining_instances
        self.remaining_host_seconds = remaining_host_seconds
        self.timeout_s = timeout_s
        self.attempts = []
        self.save()

    def snapshot(self):
        return {
            "instances_charged": len(self.attempts),
            "host_seconds_charged": sum(record["occupied_s"] for record in self.attempts),
            "remaining_instances_supplied": self.remaining_instances,
            "remaining_host_seconds_supplied": self.remaining_host_seconds,
            "per_invocation_timeout_s": self.timeout_s,
            "attempts": self.attempts,
        }

    def save(self):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.snapshot(), indent=2, allow_nan=False) + "\n")
        temporary.replace(self.path)

    def require_capacity(self, instances=1):
        state = self.snapshot()
        if (state["instances_charged"] + instances > self.remaining_instances
                or state["host_seconds_charged"] + instances * self.timeout_s > self.remaining_host_seconds):
            raise ValueError("insufficient remaining instance/host-time allowance")

    def observe(self, binary, directory, cell, round_, profile, seed, candidate, mode,
                attempt=0, warmup_s=WARMUP_S, controller="reno", cpu_profile=False,
                platform_profile=LINUX, host_sampler=False):
        record = dict(cell=cell, round=round_, profile=profile, seed=seed, candidate=candidate,
                      mode=mode, attempt=attempt)
        return self.charge(record, lambda: run_observation(
            binary, directory, cell, round_, profile, seed, warmup_s=warmup_s, timeout_s=self.timeout_s,
            record=record, controller=controller, cpu_profile=cpu_profile,
            platform_profile=platform_profile, host_sampler=host_sampler))

    def lifecycle(self, binary, directory, candidate, controller, retired, platform_profile=LINUX):
        record = dict(candidate=candidate, mode=LIFECYCLE, attempt=0)
        return self.charge(record, lambda: run_lifecycle(
            binary, directory, controller, retired, self.timeout_s, record, platform_profile))

    def charge(self, record, run):
        """Charges one attempt durably before run launches anything, and keeps the charge
        whatever run does."""
        self.require_capacity()
        record.update(status="started", occupied_s=0, started_at_unix_ns=time.time_ns())
        self.attempts.append(record)
        self.save()  # A charge exists before either role can start.
        begun = time.monotonic()
        try:
            run()
            record["status"] = "succeeded"
            return record
        except BaseException as error:
            record.update(status="failed", error=f"{type(error).__name__}: {error}")
            raise
        finally:
            record["occupied_s"] = time.monotonic() - begun
            self.save()


def check_prerequisites(system, machine, which, platform_profile=LINUX):
    if platform_profile == DARWIN:
        if (system, machine) != PROFILES[DARWIN]["host"]:
            raise RuntimeError(f"the native profile needs Darwin arm64, not {system} {machine}")
        return
    if system != "Linux" or machine != "x86_64":
        raise RuntimeError(f"needs Linux amd64, not {system} {machine}")
    if not which("taskset"):
        raise RuntimeError("taskset is required")


def run_campaign(binary, output, candidate, log, ledger, cells=None):
    ledger.require_capacity(len(schedule(cells)))
    results = output / "observations.jsonl"
    superseded = output / "superseded.jsonl"
    keyed = {}
    for instance in schedule(cells):
        keyed.setdefault(instance[:2], []).append(instance)
    records, reruns = [], 0
    for (cell, round_), pair in keyed.items():
        attempt = 0
        while True:
            observed = []
            for _, _, profile, seed in pair:
                quiet = wait_quiet(log)
                load_before = os.getloadavg()[0]
                record = ledger.observe(binary, output / cell / f"round{round_}" / f"attempt{attempt}" / profile,
                                        cell, round_, profile, seed, candidate, "campaign", attempt=attempt)
                record.update(attempt=attempt, candidate=candidate, quiet=quiet, load_before=load_before, load_after=os.getloadavg()[0])
                observed.append(record)
                log(f"{cell} round {round_} {profile} attempt {attempt}: foreign {record['foreign_cpu_s']:.2f} s, contaminated {record['contaminated']}")
            if not rerun_due(observed, attempt, reruns):
                break
            with superseded.open("a") as file:
                for record in observed:
                    record["rerun_cause"] = "foreign CPU over the limit"
                    file.write(json.dumps(record) + "\n")
            ledger.save()
            ledger.require_capacity(len(pair))
            reruns += 1
            attempt += 1
        records += observed
        with results.open("a") as file:
            for record in observed:
                file.write(json.dumps(record) + "\n")
        if any(record["contaminated"] for record in observed):
            raise ValueError("contaminated pair has no admitted replacement")
    return records, reruns


# The candidate checkout a Darwin run binds its binary to (#1528): by default the one
# that holds this driver, which is the protocol's $SRC.
SOURCE = Path(__file__).resolve().parents[2]


def binary_identity(binary):
    path = Path(binary).resolve(strict=True)
    build = subprocess.run(["go", "version", "-m", str(path)], capture_output=True, text=True, check=True).stdout
    if not build.splitlines() or not build.splitlines()[0].endswith(": " + GO_VERSION):
        raise ValueError(f"binary must be built with {GO_VERSION}")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "build_info": build}


# MP-MAC #1569 (protocol D12 A): the Darwin X11 verdict, computed read-only from the
# accepted attempt of each protocol round N. Only the two arm records in each attempt's
# diagnostic.jsonl are inputs; summary.json embeds copies and is never read.
VERDICT_SCHEMA = "mp-mac-x11-verdict/1"
VERDICT_ROUNDS = (1, 2, 3)
VERDICT_FILES = ("diagnostic.jsonl", "identity.json")
DARWIN_JUDGED = ("protocol X11 (D12 A): R18's judge_cell arithmetic, unchanged, over the accepted attempt of "
                 "rounds 1-3 paired by N; Darwin memory in normalized bytes")
DARWIN_BBR_NOT_JUDGED = ("BBR ordinary-cost ratios are reported with judged false; the owner disposes BBR "
                         "primary/backup and aggregate cost on the exact results")


def read_json_line(text, where):
    """One verdict input: a finite JSON object, or a refusal naming where it was read."""
    def reject_nonfinite(value):
        raise ValueError(f"{where}: nonfinite JSON number {value}")
    try:
        value = json.loads(text, parse_constant=reject_nonfinite)
    except json.JSONDecodeError as error:
        raise ValueError(f"unreadable {where}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{where} is not a JSON object")
    return value


def read_json(path, where):
    try:
        text = Path(path).read_text()
    except OSError as error:
        raise ValueError(f"unreadable {where}: {error}") from error
    return read_json_line(text, where)


def check_bound(binary, source, candidate, where, name):
    """Refuse, naming where, a recorded binary ({path, sha256, build_info, binding}) whose
    #1528 binding and source snapshot are not bind()'s record of it at the candidate (#1576)."""
    binary = binary if isinstance(binary, dict) else {}
    candidate_binding.check_binding(source, binary.get("binding"), binary.get("sha256"), candidate, where, name)


def file_input(path):
    return {"path": str(path), "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}


def read_cost_attempt(n, directory):
    """One round's accepted attempt: its identity and exactly one revalidated record per arm."""
    where = f"round {n} attempt {directory}"
    identity = read_json(directory / "identity.json", f"{where} identity.json")
    try:
        lines = (directory / "diagnostic.jsonl").read_text().splitlines()
    except OSError as error:
        raise ValueError(f"{where}: unreadable diagnostic.jsonl: {error}") from error
    records = [read_json_line(line, f"{where} diagnostic.jsonl") for line in lines if line.strip()]
    if sorted(record.get("profile") for record in records) != sorted((CONTROL, OPTED_IN)):
        raise ValueError(f"{where}: diagnostic.jsonl needs exactly one unregistered and one opted-in arm record")
    if identity.get("platform_profile") != DARWIN:
        raise ValueError(f"{where}: the verdict reads darwin-arm64 attempts only")
    if identity.get("mode") != "diagnostic" or not isinstance(identity.get("cells"), list) or len(identity["cells"]) != 1:
        raise ValueError(f"{where}: not a one-cell diagnostic attempt")
    if identity.get("cpu_profile") is not False:
        raise ValueError(f"{where}: CPU profiling makes timings attribution-only")
    check_bound(identity.get("binary"), identity.get("source"), identity.get("candidate"), f"{where} identity.json", "binary")
    pair = {}
    for record in records:
        for key, expected in (("platform_profile", DARWIN), ("mode", "diagnostic"), ("candidate", identity.get("candidate")),
                              ("cell", identity["cells"][0]), ("controller", identity.get("controller")),
                              ("status", "succeeded"), ("cpu_profile", False)):
            if record.get(key) != expected:
                raise ValueError(f"{where}: {record.get('profile')} record {key} {record.get(key)!r} is not {expected!r}")
        try:
            check_observation(record)
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError(f"{where}: malformed {record.get('profile')} record in diagnostic.jsonl: {error!r}") from error
        pair[record["profile"]] = record
    return identity, (pair[CONTROL], pair[OPTED_IN])


def cost_verdict(attempts):
    """The X11 verdict record for one controller and cell, from {N: attempt directory}."""
    if sorted(attempts) != list(VERDICT_ROUNDS):
        raise ValueError(f"the verdict needs the accepted attempt of rounds 1, 2 and 3 exactly, not {sorted(attempts)}")
    # Every diagnostic invocation records internal round 0, so only the directory tells
    # one round's attempt from another's. Its identity is the file system's, not its
    # spelling: a case-insensitive volume names one directory many ways.
    seen = {}
    for n in VERDICT_ROUNDS:
        try:
            status = os.stat(attempts[n])
        except OSError as error:
            raise ValueError(f"round {n} attempt {attempts[n]} is unreadable: {error}") from error
        if (status.st_dev, status.st_ino) in seen:
            raise ValueError(f"round {n} attempt {attempts[n]} is round {seen[status.st_dev, status.st_ino]}'s attempt; "
                             "each round needs its own")
        seen[status.st_dev, status.st_ino] = n
    identities, rounds, inputs = {}, [], []
    for n in VERDICT_ROUNDS:
        directory = Path(attempts[n])
        identity, pair = read_cost_attempt(n, directory)
        identities[n] = identity
        rounds.append(pair)
        inputs.append({"round": n, "attempt": str(directory),
                       "files": {name: file_input(directory / name) for name in VERDICT_FILES}})
    first = identities[1]
    shared = {"candidate": lambda i: i.get("candidate"), "binary sha256": lambda i: i["binary"].get("sha256"),
              "controller": lambda i: i.get("controller"), "cell": lambda i: i["cells"][0]}
    for name, read in shared.items():
        values = {n: read(identity) for n, identity in identities.items()}
        if len(set(map(json.dumps, values.values()))) != 1:
            raise ValueError(f"the rounds do not share one {name}: {values}")
    controller, cell = first["controller"], first["cells"][0]
    judged = controller == "reno"
    result = judge_cell(cell, rounds, DARWIN, round_numbers=VERDICT_ROUNDS)
    verdict = {
        "schema": VERDICT_SCHEMA, "platform_profile": DARWIN, "controller": controller, "cell": cell, "mode": "diagnostic",
        "candidate": first["candidate"], "binary_sha256": first["binary"]["sha256"], "source": first["source"],
        "inputs": inputs, "judged": judged,
        "passed": result["passed"] if judged else None,
        "failures": result["failures"] if judged else [],
        "judgment": DARWIN_JUDGED if judged else DARWIN_BBR_NOT_JUDGED,
        # Reported, not decided: attempt selection and contamination belong to Q2's receipt.
        "host_activity": {str(n): {record["profile"]: record["host_activity"]["status"] for record in pair}
                          for n, pair in zip(VERDICT_ROUNDS, rounds)},
        "workload_failures": {str(n): [failure for record in pair for failure in workload_failures(record)]
                              for n, pair in zip(VERDICT_ROUNDS, rounds)},
    }
    if judged:
        verdict["diagnostic"] = result
    else:
        verdict["observations"] = {key: value for key, value in result.items() if key not in ("passed", "failures")}
    return verdict


def parse_attempts(parser, values, key):
    attempts = {}
    for value in values or ():
        name, separator, directory = value.partition("=")
        if not separator or not directory:
            parser.error(f"--attempt takes KEY=DIR, not {value!r}")
        try:
            name = key(name)
        except ValueError:
            parser.error(f"--attempt key {name!r} is not valid")
        if name in attempts:
            parser.error(f"--attempt {name} is given twice")
        attempts[name] = Path(directory)
    return attempts


def verdict_main(argv):
    parser = argparse.ArgumentParser(description="Read-only Darwin X11 ordinary-cost verdict (MP-MAC #1569, protocol D12 A)")
    parser.add_argument("--verdict", action="store_true", required=True)
    parser.add_argument("--platform-profile", choices=sorted(PROFILES), required=True)
    parser.add_argument("--attempt", action="append", metavar="N=DIR",
                        help="the accepted $N/a$A attempt directory of round N; exactly N = 1, 2 and 3")
    parser.add_argument("--output", required=True, type=Path, help="a new directory for verdict.json")
    args = parser.parse_args(argv)
    if args.platform_profile != DARWIN:
        raise ValueError("the verdict mode judges darwin-arm64 attempts only; Linux keeps R18's campaign summary")
    verdict = cost_verdict(parse_attempts(parser, args.attempt, int))
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "verdict.json").write_text(json.dumps(verdict, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: verdict[key] for key in ("controller", "cell", "judged", "passed", "failures")}))
    if verdict["judged"]:
        return 0 if verdict["passed"] else 1
    return 0 if not any(verdict["workload_failures"].values()) else 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--verdict" in argv:
        return verdict_main(argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller", choices=("reno", "bbrv3"), default="reno",
                        help="BBR runs the same workloads in smoke or diagnostic mode; the campaign stays Reno")
    parser.add_argument("--platform-profile", choices=sorted(PROFILES), default=LINUX,
                        help="darwin-arm64 records native smoke, diagnostic or lifecycle-memory observations without a verdict")
    parser.add_argument("--host-sampler", choices=("none", "powermetrics"), default="none",
                        help="darwin-arm64 only: optional powermetrics plist host activity; needs privilege the driver never acquires")
    parser.add_argument("--cpu-profile", action="store_true",
                        help="profile both diagnostic roles; timings are attribution-only, not qualification")
    parser.add_argument("--candidate", required=True, help="the exact 40-character product commit under measurement")
    parser.add_argument("--binary", required=True, help="the test binary built with -tags ordinarycost")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source", type=Path,
                        help="darwin-arm64 only: the clean candidate checkout the binary must rebuild from byte for byte; "
                             "default: the checkout holding this driver")
    parser.add_argument("--remaining-instances", required=True, type=int)
    parser.add_argument("--remaining-host-seconds", required=True, type=float)
    parser.add_argument("--timeout-seconds", required=True, type=float, help="maximum reserved duration per observation, including setup/cleanup")
    parser.add_argument("--revalidate-cell", action="append", choices=sorted(CELLS),
                        help="campaign only: rerun just this affected cell of the Reno inventory; repeatable")
    parser.add_argument("--cause", help="the concrete source change that affects each --revalidate-cell")
    modes = parser.add_mutually_exclusive_group()
    every_cell = sorted(set(CELLS) | set(NATIVE_CELLS))
    modes.add_argument("--smoke-cell", choices=every_cell, help="one short diagnostic pair; never counted campaign evidence")
    modes.add_argument("--diagnostic-cell", choices=every_cell, help="one 10s/60s diagnostic pair; never counted campaign evidence")
    modes.add_argument("--lifecycle-memory", action="store_true",
                       help="one negotiated idle/backup/retired memory observation through public admission; readiness only")
    parser.add_argument("--retired-lifecycle", choices=LIFECYCLE_RETIRED,
                        help="--lifecycle-memory only: the one qualifying retirement state to sample")
    args = parser.parse_args(argv)
    if args.lifecycle_memory != bool(args.retired_lifecycle):
        parser.error("--lifecycle-memory and --retired-lifecycle go together")
    if args.lifecycle_memory:
        if args.cpu_profile or args.revalidate_cell or args.host_sampler != "none":
            parser.error("--lifecycle-memory takes no CPU profile, revalidation or host sampler")
    native = args.platform_profile == DARWIN
    cell_choice = args.smoke_cell or args.diagnostic_cell
    if cell_choice and cell_choice not in PROFILES[args.platform_profile]["cells"]:
        parser.error(f"{cell_choice} is not in the {args.platform_profile} inventory")
    if native and not (cell_choice or args.lifecycle_memory):
        parser.error("the native profile records smoke, diagnostic or lifecycle-memory observations; "
                     "Q1 selects any campaign protocol")
    if args.host_sampler != "none" and not native:
        parser.error("--host-sampler belongs to the native profile")
    if args.source is not None and not native:
        parser.error("--source belongs to the native profile")
    check_prerequisites(platform.system(), platform.machine(), shutil.which, args.platform_profile)
    if len(args.candidate) != 40 or any(c not in "0123456789abcdef" for c in args.candidate):
        parser.error("--candidate must be a full lowercase commit SHA")
    if args.controller == "bbrv3" and not cell_choice and not args.lifecycle_memory:
        parser.error("BBR runs smoke or diagnostic cells; the campaign inventory stays Reno")
    if args.cpu_profile and not cell_choice:
        parser.error("CPU profiling requires diagnostic or smoke mode")
    if args.revalidate_cell and cell_choice:
        parser.error("--revalidate-cell selects campaign cells")
    if bool(args.revalidate_cell) != bool(args.cause):
        parser.error("--revalidate-cell and --cause go together")
    binary = binary_identity(args.binary)
    if native:
        # Before any output or launch, and outside the ledger and every timeout (#1528).
        bound = candidate_binding.bind(args.source or SOURCE, args.candidate, {"binary": binary["path"]})
        binary["binding"] = bound["bindings"]["binary"]
    args.output.mkdir(parents=True, exist_ok=False)
    mode = ("smoke" if args.smoke_cell else "diagnostic" if args.diagnostic_cell
            else LIFECYCLE if args.lifecycle_memory else "campaign")
    warmup = 2 if mode == "smoke" else WARMUP_S
    identity = {
        "candidate": args.candidate, "binary": binary, "controller": args.controller,
        "platform_profile": args.platform_profile,
        "cpu_profile": args.cpu_profile, "timing_eligible": not args.cpu_profile,
        "comparator": {"candidate": args.candidate, "binary_sha256": binary["sha256"], "profile": CONTROL},
        "kernel": platform.platform(), "uname": " ".join(platform.uname()), "go": GO_VERSION,
        "warmup_s": warmup, "window_s": WINDOW_S, "base_seed": BASE_SEED, "mode": mode,
        "cells": [cell_choice] if native else schedule_cells(args.revalidate_cell), "revalidation_cause": args.cause,
        "remaining_instances": args.remaining_instances, "remaining_host_seconds": args.remaining_host_seconds,
        "per_invocation_timeout_s": args.timeout_seconds, "metric_boundaries": METRIC_BOUNDARIES,
    }
    if args.lifecycle_memory:
        # No window, seed or ordinary comparator: the record's own phases carry its baseline.
        for key in ("comparator", "warmup_s", "window_s", "base_seed"):
            del identity[key]
        identity.update(cells=[], workload=LIFECYCLE, retired_lifecycle=args.retired_lifecycle,
                        lifecycle_phases=LIFECYCLE_PHASES, lifecycle_boundaries=LIFECYCLE_BOUNDARIES)
    if native:
        identity.update(macos=platform.mac_ver()[0], pinning="none: Darwin offers no CPU affinity",
                        host_sampler=args.host_sampler, source=bound["source"])
    else:
        identity.update(server_cpus=SERVER_CPUS, client_cpus=CLIENT_CPUS, fixture_cpus_and_siblings=FIXTURE_CPUS)
    (args.output / "identity.json").write_text(json.dumps(identity, indent=2) + "\n")

    def log(message):
        line = f"{time.strftime('%H:%M:%S')} {message}"
        print(line, flush=True)
        with (args.output / "campaign.log").open("a") as file:
            file.write(line + "\n")

    def interrupt_on_sigterm(signum, frame):
        # Use the same unwind path as an operator interrupt: reap roles, then persist charges.
        raise KeyboardInterrupt("SIGTERM")

    previous_sigterm = signal.signal(signal.SIGTERM, interrupt_on_sigterm)
    ledger = None
    summary = {"passed": False, "mode": mode, "campaign_complete": False, "metric_boundaries": METRIC_BOUNDARIES,
               "controller": args.controller, "cpu_profile": args.cpu_profile, "timing_eligible": not args.cpu_profile,
               "platform_profile": args.platform_profile}
    try:
        ledger = AttemptLedger(args.output, args.remaining_instances, args.remaining_host_seconds, args.timeout_seconds)
        if mode == LIFECYCLE:
            if args.timeout_seconds < LIFECYCLE_TIMEOUT_S:
                raise ValueError(f"a lifecycle observation needs at least {LIFECYCLE_TIMEOUT_S} s")
        elif args.timeout_seconds < SETUP_S + warmup + WINDOW_S + 10:
            raise ValueError("timeout does not cover setup, warmup, window and fixture cleanup")
        if mode == LIFECYCLE:
            # One attempt, no rerun: a failed observation fails the run.
            record = ledger.lifecycle(binary["path"], args.output / LIFECYCLE, args.candidate,
                                      args.controller, args.retired_lifecycle, args.platform_profile)
            with (args.output / f"{LIFECYCLE}.jsonl").open("a") as file:
                file.write(json.dumps(record) + "\n")
            summary.update(passed=True, judged=False, judgment=LIFECYCLE_NOT_JUDGED,
                           retired_lifecycle=args.retired_lifecycle,
                           go_heap_live={sample["phase"]: sample["go_heap_live"]["value"]
                                         for sample in record["client"]["samples"]})
        elif mode == "campaign":
            records, reruns = run_campaign(binary["path"], args.output, args.candidate, log, ledger,
                                           args.revalidate_cell)
            summary.update(summarize(records, args.revalidate_cell), reruns=reruns,
                           campaign_complete=True, selected_cells=schedule_cells(args.revalidate_cell))
        else:
            cell = cell_choice
            profiles = [CONTROL, OPTED_IN]
            ledger.require_capacity(len(profiles))
            records = []
            for profile in profiles:
                quiet = ({"available": False, "reason": "no quiet-host test on the native profile"}
                         if native else wait_quiet(log))
                record = ledger.observe(binary["path"], args.output / cell / profile, cell, 0,
                                        profile, BASE_SEED, args.candidate, mode, warmup_s=warmup,
                                        controller=args.controller, cpu_profile=args.cpu_profile,
                                        platform_profile=args.platform_profile,
                                        host_sampler=args.host_sampler == "powermetrics")
                record["quiet"] = quiet
                records.append(record)
                with (args.output / f"{mode}.jsonl").open("a") as file:
                    file.write(json.dumps(record) + "\n")
            if native:
                # Every record already passed check_observation; there is no threshold verdict,
                # but a failed workload fails the semantic smoke.
                failures = [failure for record in records for failure in workload_failures(record)]
                summary.update(passed=not failures, judged=False, judgment=NATIVE_NOT_JUDGED,
                               observations=len(records), workload_failures=failures)
            else:
                verdict = judge_cell(cell, [tuple(records)])
                contaminated = sum(r["contaminated"] for r in records)
                judged = args.controller == "reno" or cell == "stateless-pressure"
                summary.update(judged=judged, contaminated_observations=contaminated)
                if judged:
                    summary.update(passed=verdict["passed"] and not contaminated, diagnostic=verdict)
                else:
                    # Ratios only: no threshold outcome is reported, but a failed transfer fails.
                    failures = [failure for record in records for failure in workload_failures(record)]
                    observations = {k: v for k, v in verdict.items() if k not in ("passed", "failures")}
                    summary.update(passed=not failures and not contaminated, judgment=BBR_NOT_JUDGED,
                                   observations=observations, workload_failures=failures)
    except (Exception, KeyboardInterrupt) as error:
        summary.update(passed=False, error=f"{type(error).__name__}: {error}")
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        if ledger:
            ledger.save()
            summary.update(ledger.snapshot())
        (args.output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    log(f"done: mode {mode}, passed {summary['passed']}, charged {summary.get('instances_charged', 0)}")
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
