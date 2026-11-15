#!/usr/bin/env python3
"""Read-only audit of issue #1368's frozen B5 final ordinary campaign.

No workloads are launched. The original CPU ceiling and raw verdict are preserved;
the owner's residual-CPU exception is reported separately, never auto-approved.
"""
import argparse
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import types

PIN = 'a1c9442f110cca36cb4752b39ce24ae998d76f05'
SELECTED = '59ca2a3a3d6dc9419f9bd09ae4b1e6197153e103'
HISTORICAL = '4e80d3cf4fa7454ffc3e2a46655afd5f81f86313'
DRIVER = 'docs/audits/2026-11-14-bbr-ordinary-cost-1368/qualification/ordinary_cost_b5.py'
DRIVER_HASH = '37433087ea2b921bc47ed5603d52d7d55939347fbcab7208e62de3a6885f3d03'
E09_RATIO = 1.1569072171177908


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text(), parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON: ' + value)))


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def sha(data):
    return hashlib.sha256(data).hexdigest()


def key(record):
    return tuple(record[name] for name in ('cell', 'round', 'attempt', 'profile'))


def metrics(record):
    ordinary = next(flow for flow in record['client']['flows'] if flow['label'] == 'ordinary')
    background = sum(flow['useful_bytes'] for flow in record['client']['flows'] if flow['label'] == 'background')
    total = sum(flow['useful_bytes'] for flow in record['client']['flows'])
    require(total == ordinary['useful_bytes'] + background, 'unexpected flow label')
    return {
        'cell': record['cell'], 'round': record['round'], 'attempt': record['attempt'], 'profile': record['profile'],
        'ordinary_useful_bytes': ordinary['useful_bytes'], 'background_useful_bytes': background,
        'all_useful_bytes_cpu_denominator': total,
        'ordinary_goodput_gbit_s': ordinary['useful_bytes'] * 8 / 60 / 1e9,
        'all_flow_goodput_gbit_s': total * 8 / 60 / 1e9,
        'server_window_cpu_s': record['server']['window_cpu_s'],
        'client_window_cpu_s_descriptive_only': record['client']['window_cpu_s'],
        'server_cpu_ns_per_all_useful_byte': record['server']['window_cpu_s'] / total * 1e9,
        'foreign_cpu_s': record['foreign_cpu_s'], 'stored_contaminated': record['contaminated'],
        'foreign_limit_at_final_charged_duration': .05 * record['occupied_s'],
        'occupied_s': record['occupied_s'], 'quiet': record['quiet'],
        'control_p99_us': ordinary['control']['p99_us'],
        'send_p99_us': record['server']['application_send_call']['ordinary']['p99_us'],
        'rss_kb_at_20s': record['server']['rss_kb_at_20s'], 'rss_kb_end': record['server']['rss_kb_end'],
        'all_flow_empty_seconds': sum(value == 0 for flow in record['client']['flows'] for value in flow['series']),
        'packets_lost': sum(item.get('packets_lost', 0) for item in record['server']['connections']),
        'datagram_drops': sum(item.get('datagram_drops', 0) for item in record['client']['flows']),
        'unprocessed_drops': sum(item.get('unprocessed_drops', 0) for item in record['client']['flows']),
        'write_errors': record['server']['write_errors'],
        'timeout_closes': sum(bool(item['timeout_close']) for item in record['server']['connections'] + record['client']['flows']),
        'nonempty_close_causes': [item['close_cause'] for item in record['server']['connections'] + record['client']['flows'] if item['close_cause']],
        'joined': record['server']['joined'], 'flood': record['client'].get('flood'),
    }


def audit(args):
    git = lambda *command: subprocess.check_output(['git', '-C', str(args.repo), *command])
    source = git('show', PIN + ':' + DRIVER)
    require(sha(source) == DRIVER_HASH, 'frozen driver hash differs')
    require(source == git('show', HISTORICAL + ':interop/multipath/ordinary_cost.py'), 'historical driver differs')
    driver = types.ModuleType('frozen_b5_audit')
    exec(compile(source, 'frozen_b5_ordinary_cost.py', 'exec'), driver.__dict__)
    require((driver.ROUNDS, driver.GOODPUT_FLOOR, driver.CPU_CEILING, driver.MAX_RERUN_PAIRS) == (3, .95, 1.10, 3), 'frozen constants changed')
    raw = args.raw
    summary, ledger, identity = [read(raw / name) for name in ('summary.json', 'ledger.json', 'identity.json')]
    attempts, retained, superseded = ledger['attempts'], lines(raw / 'observations.jsonl'), lines(raw / 'superseded.jsonl')
    require(summary['attempts'] == attempts, 'summary and ledger attempts differ')
    require(identity['mode'] == summary['mode'] == 'campaign', 'diagnostics cannot qualify')
    require(identity['controller'] == 'bbrv3' and identity['cells'] == list(driver.BBR_CELLS), 'wrong inventory/controller')
    require(identity['revalidation_cause'] is None, 'unexpected subset revalidation')
    require(identity['warmup_s'] == 10 and identity['window_s'] == 60 and identity['base_seed'] == 1038, 'window or seed changed')
    require(identity['server_cpus'] == '8-11' and identity['client_cpus'] == '12-15', 'affinity changed')
    require(identity['fixture_cpus_and_siblings'] == driver.FIXTURE_CPUS, 'sibling coverage changed')
    require(identity['metric_boundaries'] == summary['metric_boundaries'] == driver.METRIC_BOUNDARIES, 'metric boundary changed')
    require(identity['go'] == driver.GO_VERSION and identity['per_invocation_timeout_s'] == 135, 'toolchain/timeout changed')
    require(identity['comparator'] == {'candidate': identity['candidate'], 'binary_sha256': identity['binary']['sha256'], 'profile': driver.CONTROL}, 'controller-matched comparator identity changed')
    changed = git('diff', '--name-only', SELECTED, identity['candidate'], '--', '*.go', 'go.mod', 'go.sum').decode().splitlines()
    require(not changed, 'qualification Go/module source differs from selected E09: ' + repr(changed))
    manifest, build = read(args.manifest), read(args.build_receipt)
    require(manifest['product_sha'] == build['product_sha'] == identity['candidate'], 'source identity mismatch')
    require(build['binary_sha256'] == identity['binary']['sha256'] and build['exit_code'] == 0, 'binary/build identity mismatch')
    require(build['manifest_sha256'] == sha(args.manifest.read_bytes()), 'build manifest digest mismatch')
    require(manifest['historical_driver_sha256'] == DRIVER_HASH and manifest['historical_driver_revision'] == HISTORICAL, 'wrong bundle driver')
    require(manifest['public_enablement'] is False and build['public_enablement'] is False, 'unexpected public enablement')
    preparer_path = DRIVER.rsplit('/', 1)[0] + '/prepare.py'
    preparer_source = git('show', PIN + ':' + preparer_path)
    preparer = types.ModuleType('pinned_preparer_audit')
    exec(compile(preparer_source, 'pinned_prepare.py', 'exec'), preparer.__dict__)
    originals = {name: git('show', identity['candidate'] + ':' + name) for name in preparer.EXPECTED}
    replacements = preparer.replacements(originals)
    expected_overlay = {name: {'original_sha256': sha(originals[name]), 'replacement_sha256': sha(value)} for name, value in replacements.items()}
    require(manifest['overlay_files'] == expected_overlay, 'overlay source scope/hash differs')
    require(manifest['generator_sha256'] == sha(preparer_source), 'bundle generator differs')
    require(manifest['build_helper_sha256'] == sha(git('show', PIN + ':' + DRIVER.rsplit('/', 1)[0] + '/build.py')), 'build helper differs')
    require(build['go_version'] == 'go version go1.27.4 linux/amd64', 'native toolchain differs')
    require(build['environment'] == {'GOOS': 'linux', 'GOARCH': 'amd64', 'CGO_ENABLED': '0', 'GOAMD64': 'v1', 'GOEXPERIMENT': '', 'GOTOOLCHAIN': 'local', 'GOENV': 'off', 'GOFLAGS': '', 'GOWORK': 'off'}, 'build environment differs')
    require(build['command'][:2] == ['go', 'test'] and len(build['command']) == 9 and build['command'][2].startswith('-overlay=') and build['command'][3:7] == ['-tags', 'ordinarycost', '-c', '-o'] and build['command'][-1] == '.', 'build command differs')
    require(manifest['qualification'] == {'controller': 'bbrv3', 'cells': ['mixed-bulk', 'stateless-pressure'], 'profiles': ['unregistered', 'opted-in'], 'rounds': 3, 'planned_observations': 12}, 'bundle inventory differs')
    require(not list(raw.rglob('*.pprof')), 'profile artifact in uninstrumented campaign')
    require(len(attempts) <= 18 and ledger['instances_charged'] == summary['instances_charged'] == len(attempts), 'attempt accounting differs')
    occupied = sum(record['occupied_s'] for record in attempts)
    require(occupied == ledger['host_seconds_charged'] == summary['host_seconds_charged'], 'host-time accounting differs')
    require(ledger['remaining_instances_supplied'] == identity['remaining_instances'] == 420 - args.prior_instances, 'remaining instance allowance differs')
    require(math.isclose(ledger['remaining_host_seconds_supplied'], float(Decimal(28800) - args.prior_host_seconds), abs_tol=1e-9), 'prior host-time allowance differs')
    require(ledger['remaining_host_seconds_supplied'] == identity['remaining_host_seconds'], 'identity/ledger allowance differs')
    require(ledger['per_invocation_timeout_s'] == 135, 'ledger timeout changed')
    indexed = {key(record): record for record in attempts}
    require(len(indexed) == len(attempts), 'duplicate ledger attempt identity')
    for record in retained + superseded:
        require(indexed.get(key(record)) == record, 'jsonl and ledger raw record differ')
    expected_order, evidence = [], []
    scheduled = driver.schedule('bbrv3')
    for cell, round_, _, _ in scheduled[::2]:
        group = [record for record in attempts if record['cell'] == cell and record['round'] == round_]
        if not group:
            continue
        for attempt in sorted(set(record['attempt'] for record in group)):
            require(attempt in (0, 1), 'more than one replacement for a pair')
            pair = [record for record in group if record['attempt'] == attempt]
            order = (driver.CONTROL, driver.OPTED_IN) if round_ % 2 == 0 else (driver.OPTED_IN, driver.CONTROL)
            require([record['profile'] for record in pair] == list(order[:len(pair)]), 'alternating order differs')
            require(len(pair) in (1, 2), 'unexpected pair size')
            expected_order += pair
            if attempt == 1:
                original = [record for record in group if record['attempt'] == 0]
                require(len(original) == 2 and any(record.get('contaminated') for record in original), 'replacement without original contamination')
                require(all(record in superseded for record in original), 'replacement lost superseded evidence')
    require(expected_order == attempts, 'attempt execution order differs from fixed schedule')
    replacement_pairs = {(record['cell'], record['round']) for record in attempts if record['attempt'] == 1}
    superseded_pairs = {(record['cell'], record['round']) for record in superseded}
    require(len(replacement_pairs) <= 3 and len(superseded_pairs) <= 3 and replacement_pairs <= superseded_pairs, 'replacement budget/evidence differs')
    for cell, round_ in superseded_pairs:
        pair = [record for record in superseded if record['cell'] == cell and record['round'] == round_]
        require(len(pair) == 2 and all(record['attempt'] == 0 and record.get('rerun_cause') == 'foreign CPU over the limit' for record in pair) and any(record['contaminated'] for record in pair), 'invalid superseded pair')
    pending_replacement = superseded_pairs - replacement_pairs
    require(not pending_replacement or (not summary['campaign_complete'] and len(pending_replacement) == 1 and pending_replacement == {(attempts[-1]['cell'], attempts[-1]['round'])}), 'unexplained superseded pair without replacement')
    previous_start = -1
    for record in attempts:
        require(record['candidate'] == identity['candidate'] and record['controller'] == 'bbrv3' and record['mode'] == 'campaign', 'attempt identity differs')
        require((record['cell'], record['round'], record['profile'], record['seed']) in scheduled, 'attempt seed/inventory differs')
        require(record['started_at_unix_ns'] > previous_start, 'nonsequential start times')
        previous_start = record['started_at_unix_ns']
        require(math.isfinite(record['occupied_s']) and record['occupied_s'] >= 0, 'invalid occupied duration')
        if record['status'] != 'succeeded':
            evidence.append({'key': key(record), 'status': record['status'], 'error': record.get('error'), 'occupied_s': record['occupied_s']})
            continue
        require(record['exit'] == {'server': 0, 'client': 0}, 'role exit mismatch')
        directory = raw / record['cell'] / f"round{record['round']}" / f"attempt{record['attempt']}" / record['profile']
        for role in ('server', 'client'):
            require(read(directory / (role + '.json')) == record[role], 'role JSON differs from ledger')
            driver.check_role_log(role, (directory / (role + '.log')).read_text())
            usage = record[role]['window_rusage']
            require(all(usage['end'][name] - usage['start'][name] == value and value >= 0 for name, value in usage['delta'].items()), 'rusage delta differs')
            require((usage['delta']['user_cpu_ns'] + usage['delta']['system_cpu_ns']) / 1e9 == record[role]['window_cpu_s'], 'CPU boundary differs')
            require(record[role]['controller'] == 'bbrv3', 'role controller differs')
        driver.check_observation(record)
        require(all('bbr_observation' not in item for item in record['server']['connections'] + record['client']['flows']), 'observer records present')
        require(record['quiet']['fixture_busy_share'] < .05, 'original quiet gate not met')
        require(0 <= record['quiet']['waited_s'] <= 7200, 'quiet wait bound differs')
        # Original classification uses a slightly shorter inner duration; do not
        # replace its stored flag with the final outer ledger duration.
        require(record['contaminated'] or record['foreign_cpu_s'] <= driver.foreign_limit_s(record['occupied_s']), 'clean flag contradicts even the outer duration')
        evidence.append(metrics(record))
    completed = summary['campaign_complete']
    verdict = None
    comparisons = {}
    if completed:
        require(len(retained) == 12 and not any(record['contaminated'] for record in retained), 'incomplete/contaminated retained inventory')
        require(len(retained) + len(superseded) == len(attempts), 'unrepresented operational attempts')
        require(summary['reruns'] == len(replacement_pairs), 'rerun count mismatch')
        verdict = driver.summarize(retained, 'bbrv3')
        require(all(summary[name] == value for name, value in verdict.items()), 'full original verdict differs')
        for cell in driver.BBR_CELLS:
            pairs = []
            for round_ in range(3):
                pair = {record['profile']: record for record in retained if record['cell'] == cell and record['round'] == round_}
                base, granted = metrics(pair[driver.CONTROL]), metrics(pair[driver.OPTED_IN])
                pairs.append({'round': round_, 'control': base, 'granted': granted,
                              'goodput_ratio': granted['ordinary_useful_bytes'] / base['ordinary_useful_bytes'],
                              'cpu_per_all_useful_byte_ratio': granted['server_cpu_ns_per_all_useful_byte'] / base['server_cpu_ns_per_all_useful_byte']})
            ratios = [pair['cpu_per_all_useful_byte_ratio'] for pair in pairs]
            expected = verdict['cells'][cell]
            require(all(math.isclose(a, b, rel_tol=1e-14) for a, b in zip(ratios, expected['cpu_per_useful_byte_ratio']['rounds'])), 'independent all-byte CPU formula differs')
            require([pair['goodput_ratio'] for pair in pairs] == expected['goodput_ratio']['rounds'], 'independent ordinary goodput formula differs')
            comparisons[cell] = {'pairs': pairs, 'cpu_ratios': {'median': statistics.median(ratios), 'range': [min(ratios), max(ratios)]},
                                 'non_cpu_original_failures': [failure for failure in expected['failures'] if not failure.startswith('CPU per useful byte ratio ')],
                                 'cpu_original_failures': [failure for failure in expected['failures'] if failure.startswith('CPU per useful byte ratio ')]}
        old = [json.loads(line) for line in git('show', PIN + ':docs/audits/2026-11-14-bbr-ordinary-cost-1368/e09-window2-timing/diagnostic.jsonl').decode().splitlines()]
        comparisons['prior_valid_E09_stateless_pair_descriptive_only'] = {'cpu_ratio': E09_RATIO, 'observations': [metrics(record) for record in old],
            'interpretation': 'A prior single pair is descriptive context, not a new numeric ceiling. Mixed-bulk has different background work and must not be treated as a direct like-for-like stateless comparison.'}
    else:
        require(summary['passed'] is False, 'incomplete campaign claims pass')
    charge = Decimal(str(ledger['host_seconds_charged']))
    return {'audit_source_pin': PIN, 'selected_Go_module_equivalence': SELECTED, 'driver_sha256': DRIVER_HASH,
            'runtime_source': identity['candidate'], 'binary_sha256': identity['binary']['sha256'],
            'audit_checks': 'passed', 'campaign_complete': completed, 'original_raw_verdict': verdict,
            'incomplete_error': summary.get('error'), 'retained_observations': len(retained), 'superseded_observations': len(superseded),
            'replacement_pairs': len(replacement_pairs), 'superseded_pairs_without_launched_replacement': sorted(pending_replacement), 'observations': evidence, 'comparisons': comparisons,
            'owner_exception': {'accepted_reference_cpu_ratio': E09_RATIO, 'original_cpu_ceiling_unchanged': 1.10,
                               'source': PIN, 'automatic_acceptance': False,
                               'scope': 'Residual E09 CPU cost only. Qualification validity, non-CPU requirements, material-worsening review, six interop cases and review/hosted checks remain separate.'},
            'charge': {'instances': len(attempts), 'host_seconds': str(charge),
                       'cumulative_instances': args.prior_instances + len(attempts),
                       'cumulative_host_seconds': str(args.prior_host_seconds + charge),
                       'remaining_instances': 420 - args.prior_instances - len(attempts),
                       'remaining_host_seconds': str(Decimal(28800) - args.prior_host_seconds - charge)},
            'limitations': ['Foreign CPU source schedstat/softirq endpoints are not saved. Stored original contamination flags remain authoritative; final ledger occupied duration is slightly longer than the inner classification interval.',
                            'The historical verdict reports loss/drop totals but does not itself fail on every nonzero counter. Those raw counters are exposed for the separately required correctness interpretation; no thresholds are invented here.',
                            'Assess material worsening using all three paired values, range/consistency, granted absolute CPU per all useful byte and output, comparator movement and background progress. Do not turn the E09 reference or sampling variation into an invented numeric acceptance ceiling.',
                            'Build/setup charges are supplied in the prior cumulative total and must be independently reconciled to their setup receipts. This audit adds operational attempt charges only.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path('/Users/josh/code/github.com/the-sarge/quic-go-fast'))
    parser.add_argument('--raw', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--build-receipt', type=Path, required=True)
    parser.add_argument('--prior-instances', type=int, required=True)
    parser.add_argument('--prior-host-seconds', type=Decimal, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args), indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
