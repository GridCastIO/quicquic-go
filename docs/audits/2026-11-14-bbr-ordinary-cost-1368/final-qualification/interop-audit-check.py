#!/usr/bin/env python3
"""Frozen B5 artifact + synthetic receipt checks; no operational test execution."""
import copy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile
import types

spec = importlib.util.spec_from_file_location('audit', '/tmp/qgf-final-interop-audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
repo = Path('/Users/josh/code/github.com/the-sarge/quic-go-fast')
git = lambda *args: subprocess.check_output(['git', '-C', str(repo), *args])
historical = 'docs/audits/2026-11-14-multipath-b5/interop/'
manifest = json.loads(git('show', audit.PIN + ':docs/audits/2026-11-14-bbr-ordinary-cost-1368/final-qualification/interop/manifest.json'))
driver = types.ModuleType('driver')
exec(compile(git('show', audit.PIN + ':' + audit.ROOT + 'run_b5.py'), 'run_b5', 'exec'), driver.__dict__)

def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + '\n')

checks = []
with tempfile.TemporaryDirectory(prefix='qgf-interop-audit-check-') as td:
    root = Path(td)
    bundle, results, receipts = root / 'bundle', root / 'results', root / 'receipts'
    bundle.mkdir(); results.mkdir(); receipts.mkdir()
    write(bundle / 'manifest.json', manifest)
    image = 'sha256:' + 'a' * 64
    build = {'product_sha': manifest['product_sha'], 'manifest_sha256': audit.sha((bundle / 'manifest.json').read_bytes()),
             'identity': {'QGF_SOURCE_COMMIT': manifest['product_sha'], 'QGF_SOURCE_TREE': manifest['product_tree'], 'QGF_IMAGE_ID': image},
             'peer_binary_sha256': 'b' * 64, 'binary_sha256': 'c' * 64,
             'command': ['go', 'test', '-overlay=/bundle/overlay.json', '-tags', 'picoquic', '-c', '-o', '/bundle/peer-matrix.test', '.'],
             'working_directory': '/product', 'environment': manifest['build_environment'], 'go_version': 'go version go1.27.4 linux/amd64',
             'public_enablement': False, 'exit_code': 0}
    write(bundle / 'build-receipt.json', build)
    (bundle / 'image-id.txt').write_text(image + '\n')
    write(bundle / 'image-inspect.json', [{'Id': image.removeprefix('sha256:'), 'Architecture': 'amd64'}])
    names = ['interop-image', 'interop-build'] + [f'interop-{scenario}-{role}' for scenario in audit.SCENARIOS for role in audit.ROLES] + ['interop-aggregate']
    now = datetime(2026, 11, 15, 5, 0, tzinfo=timezone.utc)
    remaining_i, remaining_s = 160, Decimal(16000)
    wrapper_starts = {}
    for name in names:
        is_case = name not in ('interop-image', 'interop-build', 'interop-aggregate')
        count, seconds = (1, Decimal(60)) if is_case else (0, Decimal(1))
        reserve = 150 if is_case else (0 if name == 'interop-aggregate' else 1200)
        ended = now + timedelta(seconds=float(seconds))
        r = {'command': ['synthetic-receipt-only'], 'instances_charged': count, 'remaining_instances_before': remaining_i,
             'remaining_host_seconds_before': str(remaining_s), 'reserved_host_seconds': str(reserve), 'status': 'passed', 'exit_code': 0,
             'started_utc': now.isoformat(), 'ended_utc': ended.isoformat(), 'elapsed_host_seconds': str(seconds),
             'remaining_instances_after': remaining_i - count, 'remaining_host_seconds_after': str(remaining_s - seconds)}
        write(receipts / (name + '.json'), r)
        wrapper_starts[name] = now.isoformat()
        remaining_i -= count; remaining_s -= seconds; now = ended + timedelta(seconds=1)
    for index, (scenario, role) in enumerate((s, r) for s in audit.SCENARIOS for r in audit.ROLES):
        prefix = historical + scenario + '/' + role + '/'
        result = json.loads(git('show', audit.PIN + ':' + prefix + 'result.json'))
        attempt = json.loads(git('show', audit.PIN + ':' + prefix + 'attempt.json'))
        identity = result['identity']
        identity.update(candidate=manifest['product_sha'], tree=manifest['product_tree'], image=image,
                        peer_binary_sha256=build['peer_binary_sha256'], test_binary_sha256=build['binary_sha256'])
        command, _ = driver.matrix_invocation(scenario, role, '/bundle/peer-matrix.test')
        result.update(command=command, started=wrapper_starts['interop-' + scenario + '-' + role])
        attempt.update(command=command, started=result['started'], identity=identity)
        directory = results / scenario / role
        write(directory / 'result.json', result); write(directory / 'attempt.json', attempt)
        log = git('show', audit.PIN + ':' + prefix + 'go-test.jsonl')
        (directory / 'go-test.jsonl').write_bytes(log)
        peer_name = re.search(r'retained peer evidence: [^\s"]*/(matrix-[^\\\s"]+)', log.decode()).group(1)
        peer_dir = directory / peer_name
        peer_dir.mkdir()
        (peer_dir / 'peer.log').write_bytes(git('show', audit.PIN + ':' + prefix + peer_name + '/peer.log'))
        cid = f'{index:064x}'
        write(results / scenario / (role + '.container-inspect.json'), [{'Id': cid, 'Image': image.removeprefix('sha256:'), 'State': {'ExitCode': 0, 'Running': False}}])
        (results / scenario / (role + '.container-id.txt')).write_text(cid + '\n')
    write(results / 'matrix-result.json', driver.check_matrix(results, 'bbrv3'))
    args = types.SimpleNamespace(repo=repo, bundle=bundle, results=results, receipts=receipts, prior_instances=260, prior_host_seconds=Decimal(12800))
    output = audit.audit(args)
    if not output['qualification_complete'] or output['charge']['instances'] != 6 or output['charge']['host_seconds'] != '363':
        raise AssertionError('synthetic complete fixture/accounting mismatch')
    checks.append({'case': 'six-frozen-case-shapes-and-wrapper-charge', 'passed': True})
    aggregate_path = results / 'matrix-result.json'
    aggregate = aggregate_path.read_text()
    value = json.loads(aggregate); value['identity']['test_binary_sha256'] = 'd' * 64
    write(aggregate_path, value)
    try:
        audit.audit(args)
    except ValueError as error:
        checks.append({'case': 'reject-stale-aggregate-binary', 'passed': True, 'reason': str(error)})
    else:
        raise AssertionError('accepted stale aggregate')
    aggregate_path.write_text(aggregate)
    receipt_path = receipts / 'interop-aggregate.json'
    value = json.loads(receipt_path.read_text()); value['remaining_host_seconds_after'] = str(Decimal(value['remaining_host_seconds_after']) + 1)
    write(receipt_path, value)
    try:
        audit.audit(args)
    except ValueError as error:
        checks.append({'case': 'reject-undercharged-wrapper', 'passed': True, 'reason': str(error)})
    else:
        raise AssertionError('accepted wrong charge')
print(json.dumps({'synthetic_receipts_only': True, 'frozen_case_artifacts': historical, 'operational_tests_run': 0, 'checks': checks}, indent=2))
