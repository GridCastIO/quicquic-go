#!/usr/bin/env python3
"""Observe sustained fixture-core quiet after intermittent interference.

This read-only prelaunch observation does not run a workload or modify the
ordinary-cost driver's measurement, contamination or acceptance rules.
"""

import argparse
import json
from pathlib import Path
import subprocess
import time


CPUS = list(range(8, 16)) + list(range(24, 32))
QUIET_SHARE = 0.05  # Existing ordinary-cost quiet threshold.
WAIT_LIMIT_S = 7200  # Existing ordinary-cost quiet-wait limit, no new allowance.
SAMPLE_S = 5
CONSECUTIVE_SAMPLES = 6


def running_ns():
    result = {}
    for line in Path("/proc/schedstat").read_text().splitlines():
        if line.startswith("cpu"):
            fields = line.split()
            result[int(fields[0][3:])] = int(fields[7])
    if any(cpu not in result for cpu in CPUS):
        raise RuntimeError("fixture CPU inventory is incomplete")
    return result


def processes():
    return subprocess.check_output(
        ["ps", "-eo", "pid,psr,pcpu,comm", "--sort=-pcpu"], text=True
    ).splitlines()[:12]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--consecutive-samples", type=int, default=CONSECUTIVE_SAMPLES,
                        help="five-second quiet samples required; default: %(default)s")
    args = parser.parse_args()
    if args.consecutive_samples < 1:
        parser.error("--consecutive-samples must be positive")
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    metadata = {
        "started_unix_ns": time.time_ns(),
        "fixture_cpus": CPUS,
        "quiet_share": QUIET_SHARE,
        "sample_s": SAMPLE_S,
        "consecutive_samples_required": args.consecutive_samples,
        "existing_wait_limit_s": WAIT_LIMIT_S,
        "processes_before": processes(),
        "ready": False,
        "purpose": "Supplement the two-second prelaunch sample after observed intermittent interference; original driver rules remain authoritative",
    }
    streak = 0
    samples = 0
    try:
        with (args.output / "samples.jsonl").open("x") as output:
            while time.monotonic() - started < WAIT_LIMIT_S:
                before = running_ns()
                sample_started = time.monotonic()
                time.sleep(SAMPLE_S)
                after = running_ns()
                duration = time.monotonic() - sample_started
                shares = {str(cpu): (after[cpu] - before[cpu]) / (duration * 1e9) for cpu in CPUS}
                maximum = max(shares.values())
                streak = streak + 1 if maximum < QUIET_SHARE else 0
                samples += 1
                output.write(json.dumps({"sample": samples, "unix_ns": time.time_ns(), "duration_s": duration, "shares": shares, "maximum_core_share": maximum, "quiet_streak": streak}) + "\n")
                output.flush()
                if streak == args.consecutive_samples:
                    metadata["ready"] = True
                    break
    finally:
        metadata.update(elapsed_s=time.monotonic() - started, samples=samples, quiet_streak=streak, processes_after=processes())
        (args.output / "summary.json").write_text(json.dumps(metadata, indent=2) + "\n")
        print(json.dumps({key: metadata[key] for key in ("ready", "elapsed_s", "samples", "quiet_streak")}), flush=True)
    return 0 if metadata["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
