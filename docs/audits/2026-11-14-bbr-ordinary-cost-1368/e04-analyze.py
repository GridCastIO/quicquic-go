"""Frozen E04 analysis: lifetime counters and coarse interior snapshots, not qualification."""
import collections
import json
from pathlib import Path
import statistics
import sys

root = Path(sys.argv[1])
summary = json.loads((root / 'summary.json').read_text())

def stats(values):
    return dict(min=min(values), median=statistics.median(values), max=max(values)) if values else None

def divide(n, d):
    return n / d if d else None

def emission(e):
    return dict(counters=e, refusal_fraction=divide(e['OrdinaryRefusals'], e['OrdinaryAttempts']), partial_refusal_fraction=divide(e['RefusedUsablePartialRoom'], e['OrdinaryRefusals']), handoff_bytes_mean=divide(e['HandoffBytes'], e['Handoffs']), handoff_datagrams_mean=divide(e['HandoffDatagrams'], e['Handoffs']), retry_us_mean=divide(e['RetryNanoseconds'] / 1000, e['RetryIntervals']))

def native(n):
    result = dict(counters=n)
    for name in ('OpportunityToReturn', 'ReturnToConsume'):
        d = n[name]
        result[name + '_mean_us'] = divide(d['Nanoseconds'] / 1000, d['Count'])
    return result

out = {'qualification': False, 'boundaries': 'Lifetime counters omit teardown after freeze. Interior snapshot summaries use snapshots 17–73 s after attempt registration, safely inside the approximate 5 s setup + 10 s warmup + 60 s measurement timeline. Deltas span their actual adjacent snapshot times; they are not exact measurement-window counters. Instrumentation overhead is not removed.', 'attempts': []}
for a in summary['attempts']:
    item = {k: a.get(k) for k in ('profile', 'status', 'occupied_s', 'foreign_cpu_s', 'contaminated')}
    item['roles'] = {}
    for role, entries in (('server', a['server']['connections']), ('client', a['client']['flows'])):
        entry = next(e for e in entries if e['label'] == 'ordinary')
        o = entry['bbr_observation']
        f = o['final_before_teardown']
        snaps = o['snapshots'][:o['snapshot_count']]
        inside = [s for s in snaps if 17e9 <= s['unix_ns'] - a['started_at_unix_ns'] <= 73e9]
        r = {'snapshot_count': o['snapshot_count'], 'snapshot_overflow': o['snapshot_overflow'], 'final_recorded': o['final_recorded'], 'ack_lifetime': f['recovery']['counters'], 'model_lifetime': f['model']['counters'], 'emission_lifetime': emission(f['emission']), 'native_lifetime': native(f['native']), 'interior_samples': len(inside)}
        if inside:
            r['interior_span_s'] = (inside[-1]['mono_ns'] - inside[0]['mono_ns']) / 1e9
            r['interior_phases'] = dict(collections.Counter(s['model']['phase'] for s in inside))
            for key in ('effective_pacing_rate', 'quantum', 'pending_bytes', 'current_pending_bytes'):
                r[key] = stats([s[key] for s in inside])
            for key in ('pacing_rate', 'delivery_rate', 'bandwidth', 'window', 'min_rtt_ns'):
                r['model_' + key] = stats([s['model'][key] for s in inside])
            for key in ('bytes_in_flight', 'min_rtt_ns', 'smoothed_rtt_ns'):
                r['recovery_' + key] = stats([s['recovery'][key] for s in inside])
            r['flight_fraction_of_window'] = stats([s['recovery']['bytes_in_flight'] / s['model']['window'] for s in inside if s['model']['window']])
            for name, section, nested in (('ack_delta', 'recovery', 'counters'), ('model_delta', 'model', 'counters'), ('emission_delta', 'emission', None)):
                low, high = inside[0][section], inside[-1][section]
                if nested:
                    low, high = low[nested], high[nested]
                r[name] = {k: high[k]-v for k,v in low.items() if isinstance(v,int) and not isinstance(v,bool) and 'Max' not in k and 'Min' not in k and '_max' not in k and '_min' not in k}
        item['roles'][role] = r
    out['attempts'].append(item)
print(json.dumps(out, indent=2))
