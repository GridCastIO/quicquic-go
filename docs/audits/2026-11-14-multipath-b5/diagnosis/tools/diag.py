#!/usr/bin/env python3
"""Uncounted B5 #1044 diagnosis: run one aggregation arm exactly as the campaign does,
under a sched_switch trace of the fixture CPUs, and attribute their running time by thread."""
import json, os, signal, subprocess, sys, time
from pathlib import Path
src, binary, out, arms = sys.argv[1], sys.argv[2], Path(sys.argv[3]), sys.argv[4].split(",")
window = int(sys.argv[5]) if len(sys.argv) > 5 else 60
sys.path.insert(0, f"{src}/interop/multipath")
import aggregation as agg
out.mkdir(parents=True, exist_ok=False)
here = Path(__file__).resolve().parent
for arm in arms:
    d = out / arm
    quiet = agg.wait_quiet(print)
    trace = subprocess.Popen(["sudo", "-n", "taskset", "-c", "0-3", "bpftrace", "-f", "json", "-o", str(out / f"{arm}.trace.json"), str(here / "cpu.bt")])
    time.sleep(3)
    stat_before = Path("/proc/stat").read_text()
    sched_before = agg.schedstat_running_ns()
    record = {}
    err = None
    try:
        agg.run_observation(binary, d, "balanced", 0, arm, agg.BASE_SEED, "go1.27.4", warmup_s=agg.WARMUP_S, window_s=window,
                            timeout_s=120, record=record)
    except Exception as e:
        err = repr(e)
    stat_after = Path("/proc/stat").read_text()
    sched_after = agg.schedstat_running_ns()
    subprocess.run(["sudo", "-n", "pkill", "-INT", "-f", "bpftrace -f json -o " + str(out / f"{arm}.trace.json")])
    trace.wait()
    pids = {}
    summary = {k: record.get(k) for k in ("occupied_s", "process_cpu_s", "foreign_cpu_s", "contaminated", "exit")}
    summary.update(sched_delta_ns={c: sched_after[c]-sched_before[c] for c in agg.fixture_cpus()}, arm=arm, quiet=quiet, error=err, stat_before=stat_before, stat_after=stat_after)
    (out / f"{arm}.summary.json").write_text(json.dumps(summary, indent=1, default=str) + "\n")
    print(arm, {k: summary[k] for k in ("occupied_s", "process_cpu_s", "foreign_cpu_s", "contaminated", "error")}, flush=True)
