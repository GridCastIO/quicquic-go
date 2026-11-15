#!/usr/bin/env python3
"""Synthetic artifact checks only; no Go binary or network workload is executed."""
import copy
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import types

spec = importlib.util.spec_from_file_location('audit', '/tmp/qgf-final-ordinary-audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
repo = Path('/Users/josh/code/github.com/the-sarge/quic-go-fast')
git = lambda *args: subprocess.check_output(['git', '-C', str(repo), *args])
driver = types.ModuleType('driver')
exec(compile(git('show', audit.PIN + ':' + audit.DRIVER), 'driver', 'exec'), driver.__dict__)
prior = [json.loads(line) for line in git('show', audit.PIN + ':docs/audits/2026-11-14-bbr-ordinary-cost-1368/e09-window2-timing/diagnostic.jsonl').decode().splitlines()]
prepare = types.ModuleType('prepare')
preparer_source = git('show', audit.PIN + ':' + audit.DRIVER.rsplit('/', 1)[0] + '/prepare.py')
exec(compile(preparer_source, 'prepare', 'exec'), prepare.__dict__)
originals = {name: git('show', audit.SELECTED + ':' + name) for name in prepare.EXPECTED}
replacements = prepare.replacements(originals)

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')

def jsonl(path, records):
    path.write_text(''.join(json.dumps(record) + '\n' for record in records))

def fixture(root, replacement=False):
    raw = root / 'raw'
    raw.mkdir()
    identity = json.loads(git('show', audit.PIN + ':docs/audits/2026-11-14-bbr-ordinary-cost-1368/e09-window2-timing/identity.json'))
    identity.update(candidate=audit.SELECTED, mode='campaign', cells=list(driver.BBR_CELLS), revalidation_cause=None,
                    remaining_instances=170, remaining_host_seconds=27565.0, metric_boundaries=driver.METRIC_BOUNDARIES)
    identity['comparator']['candidate'] = audit.SELECTED
    write(raw / 'identity.json', identity)
    retained, attempts, superseded = [], [], []
    for cell, round_, profile, seed in driver.schedule('bbrv3'):
        record = copy.deepcopy(prior[0 if profile == driver.CONTROL else 1])
        record.update(cell=cell, round=round_, profile=profile, seed=seed, attempt=0, candidate=audit.SELECTED,
                      mode='campaign', occupied_s=77.0, started_at_unix_ns=1000 + len(attempts), foreign_cpu_s=0.1, contaminated=False)
        for entry in record['server']['connections'] + record['client']['flows']:
            entry['controller'] = 'bbrv3'
        if cell == 'mixed-bulk':
            count = 2 if profile == driver.CONTROL else 1
            # Deliberately asymmetric background makes an ordinary-only CPU
            # denominator produce a different answer while ordinary goodput stays fixed.
            for n in range(count):
                background = copy.deepcopy(record['client']['flows'][0])
                value = 10**9 if profile == driver.CONTROL else 10**10
                background.update(label='background', useful_bytes=value * 60, series=[value] * 60,
                                  multipath_negotiated=(count == 1), paths=['live', 'live'] if count == 1 else [])
                record['client']['flows'].append(background)
                connection = copy.deepcopy(record['server']['connections'][0])
                connection['label'] = 'background'
                record['server']['connections'].append(connection)
            record['client'].pop('flood', None)
        attempts.append(record)
        retained.append(record)
    if replacement:
        original = attempts[:2]
        for record in original:
            record.update(contaminated=True, foreign_cpu_s=12.0, rerun_cause='foreign CPU over the limit')
        superseded = copy.deepcopy(original)
        replacement_pair = copy.deepcopy(original)
        for record in replacement_pair:
            record.update(attempt=1, contaminated=False, foreign_cpu_s=.1)
            record.pop('rerun_cause')
        attempts = original + replacement_pair + attempts[2:]
        retained = replacement_pair + retained[2:]
    for index, record in enumerate(attempts):
        record['started_at_unix_ns'] = 1000 + index
        directory = raw / record['cell'] / f"round{record['round']}" / f"attempt{record['attempt']}" / record['profile']
        for role in ('server', 'client'):
            write(directory / (role + '.json'), record[role])
            (directory / (role + '.log')).write_text('--- PASS: TestOrdinaryCostRole\n')
    if replacement:
        superseded = copy.deepcopy(attempts[:2])
    ledger = {'instances_charged': len(attempts), 'host_seconds_charged': 77.0 * len(attempts),
              'remaining_instances_supplied': 170, 'remaining_host_seconds_supplied': 27565.0,
              'per_invocation_timeout_s': 135, 'attempts': attempts}
    summary = dict(ledger, **driver.summarize(retained, 'bbrv3'), campaign_complete=True, mode='campaign',
                   metric_boundaries=driver.METRIC_BOUNDARIES, reruns=int(replacement))
    write(raw / 'ledger.json', ledger)
    write(raw / 'summary.json', summary)
    jsonl(raw / 'observations.jsonl', retained)
    jsonl(raw / 'superseded.jsonl', superseded)
    manifest = {'product_sha': audit.SELECTED, 'historical_driver_sha256': audit.DRIVER_HASH,
                'historical_driver_revision': audit.HISTORICAL, 'public_enablement': False,
                'qualification': {'controller': 'bbrv3', 'cells': list(driver.BBR_CELLS), 'profiles': [driver.CONTROL, driver.OPTED_IN], 'rounds': 3, 'planned_observations': 12},
                'overlay_files': {name: {'original_sha256': audit.sha(originals[name]), 'replacement_sha256': audit.sha(value)} for name, value in replacements.items()},
                'generator_sha256': audit.sha(preparer_source),
                'build_helper_sha256': audit.sha(git('show', audit.PIN + ':' + audit.DRIVER.rsplit('/', 1)[0] + '/build.py'))}
    write(root / 'manifest.json', manifest)
    build = {'product_sha': audit.SELECTED, 'binary_sha256': identity['binary']['sha256'], 'exit_code': 0,
             'manifest_sha256': audit.sha((root / 'manifest.json').read_bytes()), 'public_enablement': False,
             'go_version': 'go version go1.27.4 linux/amd64',
             'environment': {'GOOS': 'linux', 'GOARCH': 'amd64', 'CGO_ENABLED': '0', 'GOAMD64': 'v1', 'GOEXPERIMENT': '', 'GOTOOLCHAIN': 'local', 'GOENV': 'off', 'GOFLAGS': '', 'GOWORK': 'off'},
             'command': ['go', 'test', '-overlay=/synthetic/overlay.json', '-tags', 'ordinarycost', '-c', '-o', '/synthetic/binary', '.']}
    write(root / 'build-receipt.json', build)
    return types.SimpleNamespace(repo=repo, raw=raw, manifest=root / 'manifest.json', build_receipt=root / 'build-receipt.json', prior_instances=250, prior_host_seconds=Decimal(1235))

results = []
with tempfile.TemporaryDirectory(prefix='qgf-final-audit-check-') as td:
    for replacement in (False, True):
        path = Path(td) / str(replacement)
        path.mkdir()
        args = fixture(path, replacement)
        result = audit.audit(args)
        pair = result['comparisons']['mixed-bulk']['pairs'][0]
        ordinary_only = (pair['granted']['server_window_cpu_s'] / pair['granted']['ordinary_useful_bytes']) / (pair['control']['server_window_cpu_s'] / pair['control']['ordinary_useful_bytes'])
        if abs(pair['cpu_per_all_useful_byte_ratio'] - ordinary_only) < .1:
            raise AssertionError('synthetic mixed denominator did not discriminate')
        results.append({'case': 'full-with-replacement' if replacement else 'full-no-replacement', 'passed': True,
                        'mixed_all_bytes_cpu_ratio': pair['cpu_per_all_useful_byte_ratio'], 'wrong_ordinary_only_cpu_ratio': ordinary_only})
        # A fabricated verdict and an invalid rusage copy must fail audit.
        summary_path = args.raw / 'summary.json'
        original = summary_path.read_text()
        data = json.loads(original)
        data['cells']['mixed-bulk']['cpu_per_useful_byte_ratio']['median'] = ordinary_only
        write(summary_path, data)
        try:
            audit.audit(args)
        except ValueError as error:
            results.append({'case': 'reject-ordinary-only-verdict', 'passed': True, 'reason': str(error)})
        else:
            raise AssertionError('accepted wrong denominator verdict')
        summary_path.write_text(original)
        role = next(args.raw.glob('mixed-bulk/round0/attempt*/unregistered/server.json'))
        data = json.loads(role.read_text())
        data['window_rusage']['delta']['user_cpu_ns'] += 1
        write(role, data)
        try:
            audit.audit(args)
        except ValueError as error:
            results.append({'case': 'reject-mutated-role-copy', 'passed': True, 'reason': str(error)})
        else:
            raise AssertionError('accepted mutated raw role copy')
    path = Path(td) / 'stopped-before-replacement'
    path.mkdir()
    args = fixture(path, True)
    ledger = json.loads((args.raw / 'ledger.json').read_text())
    ledger['attempts'] = ledger['attempts'][:2]
    ledger.update(instances_charged=2, host_seconds_charged=154.0)
    summary = dict(ledger, passed=False, campaign_complete=False, mode='campaign', metric_boundaries=driver.METRIC_BOUNDARIES, error='ValueError: insufficient remaining instance/host-time allowance')
    write(args.raw / 'ledger.json', ledger)
    write(args.raw / 'summary.json', summary)
    jsonl(args.raw / 'observations.jsonl', [])
    output = audit.audit(args)
    if output['campaign_complete'] or output['charge']['instances'] != 2 or output['superseded_pairs_without_launched_replacement'] != [('mixed-bulk', 0)]:
        raise AssertionError('incomplete admitted replacement accounting differs')
    results.append({'case': 'preserve-superseded-pair-before-replacement-launch', 'passed': True})
print(json.dumps({'synthetic_only': True, 'native_workloads': 0, 'checks': results}, indent=2))
