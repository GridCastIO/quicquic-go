#!/usr/bin/env python3
"""X3 sampler capture and contiguity check (MP-MAC execution protocol, "Sampler capture
and contiguity check"): one bounded powermetrics capture through the owner-installed
wrapper, judged by the protocol's rules. It applies those rules and changes none of them."""

import argparse
import hashlib
import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

import ordinary_cost as driver

FORMAT = "mp-mac-x3-sampler-capture/1"
RECORDS = 60  # -n 60 in the bounded argument list
GAP_TOLERANCE_NS = 50 * 10**6
SUM_TOLERANCE_NS = 100 * 10**6
CAPTURE_DEADLINE_S = 90  # 60 one-second samples and the startup delay
CONSUMED_KEYS = ("elapsed_ns", "is_delta", "processor")  # what the adapter reads
KEPT_KEYS = ("hw_model", "kern_osversion")  # identity the recorded fixture already holds


def record_ends(raw, count):
    """The byte offset just past each of the first count records' own last byte, chunked
    as parse_powermetrics chunks them. A record's own last byte is its last non-whitespace
    byte, the last byte plistlib parses. A NUL is a separator that belongs to no record,
    wherever it falls and whichever read delivers it: the real stream places one before
    every record after the first and none after the last."""
    ends, start = [], 0
    for chunk in raw.split(b"\0"):
        if chunk.strip():
            ends.append(start + len(chunk.rstrip()))
        start += len(chunk) + 1
    return ends[:count]


def arrival(end, reads):
    """The completion time of the read that delivered byte offset end."""
    received = 0
    for at, size in reads:
        received += size
        if received >= end:
            return at
    raise ValueError(f"no read delivered byte {end}")


def receipt_elapsed(record):
    """A record's elapsed_ns for the receipt: the value when it meets the adapter's rule
    (a positive integer), otherwise null. The adapter's reason and raw bytes say why."""
    elapsed = record.get("elapsed_ns")
    return elapsed if type(elapsed) is int and elapsed > 0 else None


def key_paths(value, prefix):
    if isinstance(value, dict):
        for key, child in value.items():
            yield f"{prefix}.{key}"
            yield from key_paths(child, f"{prefix}.{key}")
    elif isinstance(value, list):
        for child in value:
            yield from key_paths(child, f"{prefix}[]")


def identity_review(records):
    """Input to X3 step 4, which decides: key names that could identify the host, beyond
    the kept model and OS fields. Names only, never values."""
    top = {key for record in records for key in record}
    return {
        "kept": list(KEPT_KEYS),
        "other_top_level_keys": sorted(top - set(CONSUMED_KEYS) - set(KEPT_KEYS)),
        "processor_key_paths": sorted({path for record in records for path in key_paths(record.get("processor"), "processor")}),
    }


def judge_capture(raw, reads, launched_ns, reaped_ns, exit, reaped, failures=()):
    """Judge one bounded capture. reads are (monotonic ns at completion, byte count) for
    each read of the sampler's output, in order; launched_ns was read just before launch
    and reaped_ns just after reaping. Status is passed, failed, or inconclusive when fewer
    than two complete deltas leave contiguity unjudged."""
    if sum(size for _, size in reads) != len(raw):
        raise ValueError("the reads do not account for the captured bytes")
    reasons = list(failures)
    if not reaped:
        reasons.append(f"the wrapper was not confirmed stopped within {driver.SAMPLER_STOP_S} s")
    elif exit != 0:
        reasons.append(f"the capture exited {exit}")
    result = {"format": FORMAT, "exit": exit, "reaped": reaped,
              "reaped_after_launch_ns": reaped_ns - launched_ns if reaped else None,
              "tolerances": {"gap_ns": GAP_TOLERANCE_NS, "sum_ns": SUM_TOLERANCE_NS, "records": RECORDS}}
    try:
        records, tail = driver.parse_powermetrics(raw)
    except ValueError as error:
        reasons.append(str(error))
        return dict(result, records=[], status="failed", reasons=reasons)
    if tail:
        reasons.append(f"{tail} bytes of a cut final record")
    arrivals = [arrival(end, reads) - launched_ns for end in record_ends(raw, len(records))]
    result.update(
        records=[{"arrival_ns": at, "elapsed_ns": receipt_elapsed(record)} for at, record in zip(arrivals, records)],
        launch_to_first_arrival_ns=arrivals[0] if arrivals else None,  # recorded, not judged
        identity_review=identity_review(records),
    )
    try:
        _, elapsed, _ = driver.delta_records(records)
    except driver.HostObservationError as error:
        reasons.append(f"the adapter rejects the capture: {error}")
        return dict(result, status="failed", reasons=reasons)
    if len(records) < 2:
        reasons.append("fewer than two complete deltas")
        return dict(result, status="failed" if len(reasons) > 1 else "inconclusive", reasons=reasons)
    if len(records) != RECORDS:
        reasons.append(f"{len(records)} records, not {RECORDS}")
    gaps = []
    for index in range(1, len(records)):
        gap = arrivals[index] - arrivals[index - 1]
        deviation = gap - elapsed[index]
        gaps.append({"record": index, "gap_ns": gap, "elapsed_ns": elapsed[index], "deviation_ns": deviation})
        if abs(deviation) > GAP_TOLERANCE_NS:
            reasons.append(f"record {index} arrived {gap / 1e9:.3f} s after record {index - 1}, "
                           f"{abs(deviation) / 1e6:.3f} ms from its {elapsed[index] / 1e9:.3f} s elapsed_ns")
    interval, total = arrivals[-1] - arrivals[0], sum(elapsed[1:])
    if abs(total - interval) > SUM_TOLERANCE_NS:
        reasons.append(f"elapsed_ns after the first record sum to {total / 1e9:.3f} s over a "
                       f"{interval / 1e9:.3f} s sampled interval")
    result.update(gaps=gaps, max_gap_deviation_ns=max(abs(gap["deviation_ns"]) for gap in gaps),
                  elapsed_after_first_ns=total, sampled_interval_ns=interval, sum_deviation_ns=total - interval)
    return dict(result, status="failed" if reasons else "passed", reasons=reasons)


def capture(directory, command=None, deadline_s=CAPTURE_DEADLINE_S):
    """Run the bounded capture through the driver's sampler route and judge it. Standard
    input stays open until the output ends, so the wrapper is never stopped early; any
    exit from this function closes it, and the wrapper then stops on its own."""
    command = command or driver.powermetrics_command("bounded")
    directory.mkdir(parents=True, exist_ok=False)
    raw_path, log_path = directory / "capture.plist", directory / "capture.log"
    chunks, reads, failures = [], [], []
    with log_path.open("wb") as log:
        launched = time.monotonic_ns()
        try:
            process = driver.launch_sampler(command, stdout=subprocess.PIPE, stderr=log)
        except OSError as error:
            process = None
            failures.append(f"the sampler never launched: {type(error).__name__}: {error}")
        if process is not None:
            try:
                deadline = time.monotonic() + deadline_s
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        failures.append(f"the capture did not end within {deadline_s} s")
                        break
                    if not select.select([process.stdout], [], [], remaining)[0]:
                        continue
                    chunk = os.read(process.stdout.fileno(), 1 << 16)
                    at = time.monotonic_ns()
                    if not chunk:
                        break
                    chunks.append(chunk)
                    reads.append((at, len(chunk)))
            except KeyboardInterrupt:
                failures.append("interrupted")
            finally:
                reaped = driver.stop_sampler(process, driver.SAMPLER_STOP_S)
                reaped_at = time.monotonic_ns()
                process.stdout.close()
    raw = b"".join(chunks)
    raw_path.write_bytes(raw)
    if process is None:
        result = {"format": FORMAT, "exit": None, "reaped": None, "records": [], "status": "failed", "reasons": failures}
    else:
        result = judge_capture(raw, reads, launched, reaped_at, process.returncode, reaped, failures)
    result.update(command=command, raw={"path": str(raw_path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()},
                  log_path=str(log_path))
    (directory / "capture.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="a new directory for the capture and its receipt")
    args = parser.parse_args(argv)
    result = capture(args.output)
    print(json.dumps({"status": result["status"], "reasons": result["reasons"],
                      "receipt": str(args.output / "capture.json")}, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
