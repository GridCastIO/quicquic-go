"""E07 diagnostic extraction: lifetime and coarse interior counters, not qualification."""

import argparse
import collections
import hashlib
import json
from pathlib import Path
import statistics


HANDOFF_UPPER_BOUNDS_BYTES = [1452, 16384, 20480, 32768, 49152, 65507, None]
DURATION_UPPER_BOUNDS_US = [10, 25, 50, 100, 250, 500, 1000, None]
INTERIOR_FIRST_NS = 17_000_000_000
INTERIOR_LAST_NS = 73_000_000_000


def stats(values):
    return dict(min=min(values), median=statistics.median(values), max=max(values)) if values else None


def divide(numerator, denominator):
    return numerator / denominator if denominator else None


def buckets(value, size, name):
    if not isinstance(value, list) or len(value) != size or any(type(v) is not int for v in value):
        raise ValueError(f"{name} must contain {size} integer counters")
    return value


def emission(value):
    counts = buckets(value["HandoffSizeBuckets"], len(HANDOFF_UPPER_BOUNDS_BYTES), "HandoffSizeBuckets")
    return {
        "counters": value,
        "refusal_fraction": divide(value["OrdinaryRefusals"], value["OrdinaryAttempts"]),
        "partial_refusal_fraction": divide(value["RefusedUsablePartialRoom"], value["OrdinaryRefusals"]),
        "handoff_bytes_mean": divide(value["HandoffBytes"], value["Handoffs"]),
        "handoff_datagrams_mean": divide(value["HandoffDatagrams"], value["Handoffs"]),
        "retry_us_mean": divide(value["RetryNanoseconds"] / 1000, value["RetryIntervals"]),
        "handoff_accounting": {
            "bucket_sum": sum(counts),
            "bucket_sum_minus_handoffs": sum(counts) - value["Handoffs"],
            "gso_plus_scalar_minus_handoffs": value["GSOHandoffs"] + value["ScalarHandoffs"] - value["Handoffs"],
        },
    }


def native(value):
    result = {
        "counters": value,
        "members_per_consumed_result": divide(value["Members"], value["ConsumeClockReads"]),
        "member_bytes_per_consumed_result": divide(value["MemberBytes"], value["ConsumeClockReads"]),
    }
    for name in ("OpportunityToReturn", "ReturnToConsume"):
        duration = value[name]
        counts = buckets(duration["Buckets"], len(DURATION_UPPER_BOUNDS_US), name + ".Buckets")
        result[name + "_mean_us"] = divide(duration["Nanoseconds"] / 1000, duration["Count"])
        result[name + "_bucket_sum_minus_count"] = sum(counts) - duration["Count"]
    return result


def counter_delta(low, high):
    """Subtract cumulative counts, including arrays, without differencing extrema or flags."""
    result = {}
    for key, value in low.items():
        if "Max" in key or "Min" in key or "_max" in key or "_min" in key:
            continue
        end = high[key]
        if type(value) is int:
            result[key] = end - value
        elif isinstance(value, list):
            left = buckets(value, len(value), key)
            right = buckets(end, len(value), key)
            result[key] = [b - a for a, b in zip(left, right)]
        elif isinstance(value, dict):
            result[key] = counter_delta(value, end)
    return result


def role_observation(observation, started_at_unix_ns):
    final = observation["final_before_teardown"]
    count = observation["snapshot_count"]
    if type(count) is not int or not 0 <= count <= len(observation["snapshots"]):
        raise ValueError("snapshot_count is outside the captured snapshot array")
    snapshots = observation["snapshots"][:count]
    inside = [s for s in snapshots if INTERIOR_FIRST_NS <= s["unix_ns"] - started_at_unix_ns <= INTERIOR_LAST_NS]
    result = {
        "snapshot_count": count,
        "snapshot_overflow": observation["snapshot_overflow"],
        "final_recorded": observation["final_recorded"],
        "ack_lifetime": final["recovery"]["counters"],
        "model_lifetime": final["model"]["counters"],
        "emission_lifetime": emission(final["emission"]),
        "native_lifetime": native(final["native"]),
        "interior_samples": len(inside),
    }
    if not inside:
        return result

    first, last = inside[0], inside[-1]
    result["interior_span_s"] = (last["mono_ns"] - first["mono_ns"]) / 1e9
    result["interior_boundaries"] = {
        "first_mono_ns": first["mono_ns"],
        "last_mono_ns": last["mono_ns"],
        "first_unix_ns": first["unix_ns"],
        "last_unix_ns": last["unix_ns"],
        "first_seconds_after_attempt_start": (first["unix_ns"] - started_at_unix_ns) / 1e9,
        "last_seconds_after_attempt_start": (last["unix_ns"] - started_at_unix_ns) / 1e9,
        "adjacent_snapshot_gaps_s": [(b["mono_ns"] - a["mono_ns"]) / 1e9 for a, b in zip(inside, inside[1:])],
        "retry_open_first": first["emission"]["RetryOpen"],
        "retry_open_last": last["emission"]["RetryOpen"],
    }
    result["interior_phases"] = dict(collections.Counter(s["model"]["phase"] for s in inside))
    for key in ("effective_pacing_rate", "quantum", "pending_bytes", "current_pending_bytes"):
        result[key] = stats([s[key] for s in inside])
    for key in ("pacing_rate", "delivery_rate", "bandwidth", "window", "min_rtt_ns"):
        result["model_" + key] = stats([s["model"][key] for s in inside])
    for key in ("bytes_in_flight", "min_rtt_ns", "smoothed_rtt_ns"):
        result["recovery_" + key] = stats([s["recovery"][key] for s in inside])
    result["flight_fraction_of_window"] = stats([s["recovery"]["bytes_in_flight"] / s["model"]["window"] for s in inside if s["model"]["window"]])
    result["ack_delta"] = counter_delta(first["recovery"]["counters"], last["recovery"]["counters"])
    result["model_delta"] = counter_delta(first["model"]["counters"], last["model"]["counters"])
    result["emission_delta"] = counter_delta(first["emission"], last["emission"])
    result["emission_interior"] = emission(result["emission_delta"])
    result["native_delta"] = counter_delta(first["native"], last["native"])
    result["native_interior"] = native(result["native_delta"])
    return result


def analyze(summary):
    output = {
        "qualification": False,
        "boundaries": "Lifetime counters include startup/warmup and omit teardown after freeze; final_recorded reports whether that freeze occurred. Interior snapshots are 17–73 seconds after attempt registration, inside the approximate 5-second setup + 10-second warmup + 60-second measurement timeline. Deltas span the first and last selected snapshot, with actual monotonic span and adjacent gaps reported; they are not exact measurement-window counters. A single selected snapshot has zero delta and zero span. Sampled gauge statistics are not time-weighted. Observer/profiler overhead is not removed.",
        "handoff_size_upper_bounds_bytes": HANDOFF_UPPER_BOUNDS_BYTES,
        "native_duration_upper_bounds_us": DURATION_UPPER_BOUNDS_US,
        "infinite_upper_bound": None,
        "proxy_limits": [
            "HandoffSizeBuckets count actual buffer bytes at emission handoff and include BBR control/probe traffic. GSOHandoffs means a nonzero GSO argument, not proof of a GSO syscall after fallback. These are not useful-byte or delivery counters.",
            "E06 permits one ordinary handoff per opportunity. Handoffs are not native request/record admissions or syscall counts: refusals, control/probe traffic, staging, pending work and result-consumption boundaries differ.",
            "ConsumeClockReads counts observed native result-record consumption under BBR. Members and MemberBytes describe the members traversed there; their ratios are consumed-record geometry proxies, not admitted/completed request rates, kernel batching or per-packet latency.",
            "OpportunityToReturn begins at reservation/opportunity time, not handoff; ReturnToConsume ends at the observer's single clock read before member recovery. The intervals include multiple stages and are not additive removable CPU time. Missing/backward timestamps are excluded from duration counts and buckets but retained as counters.",
            "RefusedUsablePartialRoom establishes credit space for at least one packet, not legality or payoff of an alternative send. Recovery sample validity and controller usable-sample counters retain their different predicates; timing-excluded and mismatched counts overlap.",
        ],
        "attempts": [],
    }
    for attempt in summary["attempts"]:
        item = {key: attempt.get(key) for key in ("profile", "status", "occupied_s", "foreign_cpu_s", "contaminated", "started_at_unix_ns")}
        item["roles"] = {}
        for role, entries in (("server", attempt["server"]["connections"]), ("client", attempt["client"]["flows"])):
            ordinary = [entry for entry in entries if entry["label"] == "ordinary"]
            if len(ordinary) != 1:
                raise ValueError(f"{attempt.get('profile')} {role}: expected one ordinary entry, got {len(ordinary)}")
            item["roles"][role] = role_observation(ordinary[0]["bbr_observation"], attempt["started_at_unix_ns"])
        output["attempts"].append(item)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path, help="E07 diagnostic directory containing summary.json")
    args = parser.parse_args()
    raw = (args.run_directory / "summary.json").read_bytes()
    output = analyze(json.loads(raw))
    output["summary_sha256"] = hashlib.sha256(raw).hexdigest()
    print(json.dumps(output, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
