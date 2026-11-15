#!/usr/bin/env python3
"""Read-only audit of the existing six BBR interop cases for issue #1368.

Imports frozen validators only; never starts containers, Go tests or peer binaries.
"""
import argparse
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import types

PIN = 'ad97d3282'
SELECTED = '59ca2a3a3d6dc9419f9bd09ae4b1e6197153e103'
ROOT = 'docs/audits/2026-11-14-bbr-ordinary-cost-1368/qualification/interop/'
DRIVER_HASH = '7de31bd73bfb026c7aa24989139fd38032c5caac730498f4967c3b5dde4c1990'
SCENARIOS = ('useful-transfer', 'abandon-reopen-late-feedback', 'same-id-migration-rebinding')
ROLES = ('client', 'server')
PEER_HASH = 'ccd8f167f2c02aa5f347324abf13bfab713bbb826dbe4ec697cc8420eb3781e4'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    def reject(value):
        raise ValueError('nonfinite JSON ' + value)
    return json.loads(Path(path).read_text(), parse_constant=reject)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def normalized_image(value):
    value = value.removeprefix('sha256:')
    require(re.fullmatch('[0-9a-f]{64}', value), 'invalid image digest')
    return 'sha256:' + value


def one_inspection(path):
    value = read(path)
    require(isinstance(value, list) and len(value) == 1, 'expected one inspection: ' + str(path))
    return value[0]


def receipts(args):
    expected = ['interop-image', 'interop-build'] + [f'interop-{scenario}-{role}' for scenario in SCENARIOS for role in ROLES] + ['interop-aggregate']
    paths = list(args.receipts.glob('interop-*.json'))
    values = [(path.stem, read(path)) for path in paths]
    values.sort(key=lambda pair: datetime.fromisoformat(pair[1]['started_utc']))
    names = [name for name, _ in values]
    require(names == expected[:len(names)], 'unexpected, duplicate, or reordered setup/case receipt inventory')
    used_instances, used_seconds = args.prior_instances, args.prior_host_seconds
    prior_end = None
    detail = []
    for name, receipt in values:
        require(receipt['elapsed_host_seconds'] is not None, 'attempt is still running: ' + name)
        seconds = Decimal(receipt['elapsed_host_seconds'])
        require(seconds.is_finite() and seconds >= 0, 'invalid elapsed occupied duration')
        instances = 0 if name in ('interop-image', 'interop-build', 'interop-aggregate') else 1
        require(receipt['instances_charged'] == instances, 'wrong instance charge: ' + name)
        require(receipt['remaining_instances_before'] == 420 - used_instances, 'nonsequential instance balance: ' + name)
        require(Decimal(receipt['remaining_host_seconds_before']) == Decimal(28800) - used_seconds, 'nonsequential time balance: ' + name)
        reserve = 1200 if name in ('interop-image', 'interop-build') else (0 if name == 'interop-aggregate' else 150)
        require(Decimal(receipt['reserved_host_seconds']) == reserve, 'existing reservation bound differs: ' + name)
        started, ended = (datetime.fromisoformat(receipt[field]) for field in ('started_utc', 'ended_utc'))
        require(ended >= started and (prior_end is None or started >= prior_end), 'overlapping/nonsequential wrapper chronology')
        prior_end = ended
        used_instances += instances
        used_seconds += seconds
        require(receipt['remaining_instances_after'] == 420 - used_instances, 'wrong post-instance balance')
        require(Decimal(receipt['remaining_host_seconds_after']) == Decimal(28800) - used_seconds, 'wrong post-time balance')
        if receipt['status'] == 'passed':
            require(receipt['exit_code'] == 0, 'passed wrapper has nonzero exit')
        else:
            require(name == names[-1], 'execution continued after failed/interrupted wrapper')
        detail.append({'name': name, 'status': receipt['status'], 'exit_code': receipt['exit_code'],
                       'instances': instances, 'host_seconds': str(seconds), 'started_utc': receipt['started_utc'],
                       'ended_utc': receipt['ended_utc'], 'command': receipt['command']})
    return values, detail, {'instances': used_instances - args.prior_instances,
                           'host_seconds': str(used_seconds - args.prior_host_seconds),
                           'cumulative_instances': used_instances, 'cumulative_host_seconds': str(used_seconds),
                           'remaining_instances': 420 - used_instances,
                           'remaining_host_seconds': str(Decimal(28800) - used_seconds)}


def audit(args):
    git = lambda *command: subprocess.check_output(['git', '-C', str(args.repo), *command])
    full_pin = git('rev-parse', PIN).decode().strip()
    source = git('show', full_pin + ':' + ROOT + 'run_b5.py')
    require(sha(source) == DRIVER_HASH and source == git('show', '4e80d3cf4fa7454ffc3e2a46655afd5f81f86313:interop/multipath/run.py'), 'frozen runner identity changed')
    driver = types.ModuleType('frozen_interop_validator')
    exec(compile(source, 'frozen_run_b5.py', 'exec'), driver.__dict__)
    manifest = read(args.bundle / 'manifest.json')
    prepare_source = git('show', full_pin + ':' + ROOT + 'prepare.py')
    prepare = types.ModuleType('pinned_interop_preparer')
    exec(compile(prepare_source, 'pinned_interop_prepare.py', 'exec'), prepare.__dict__)
    candidate = manifest['product_sha']
    require(manifest['product_tree'] == git('rev-parse', candidate + '^{tree}').decode().strip(), 'candidate tree differs')
    require(not git('diff', '--name-only', SELECTED, candidate, '--', '*.go', 'go.mod', 'go.sum').strip(), 'candidate differs from selected E09 Go/modules')
    originals = {name: git('show', candidate + ':' + name) for name in prepare.EXPECTED}
    replacements = prepare.replacements(originals)
    require(manifest['overlay_files'] == {name: {'original_sha256': sha(originals[name]), 'replacement_sha256': sha(value)} for name, value in replacements.items()}, 'overlay identities differ')
    require(manifest['unchanged_scenario_sources'] == prepare.UNCHANGED, 'scenario identity declaration differs')
    for name, digest in prepare.UNCHANGED.items():
        require(sha(git('show', candidate + ':' + name)) == digest, 'scenario/peer/build source differs: ' + name)
    require(manifest['generator_sha256'] == sha(prepare_source), 'generator differs')
    require(manifest['bundle_files']['run_b5.py'] == DRIVER_HASH and manifest['bundle_files']['peer.c'] == PEER_HASH, 'runner/peer-driver manifest differs')
    require(manifest['bundle_files']['build.py'] == sha(git('show', full_pin + ':' + ROOT + 'build.py')), 'build helper differs')
    require(manifest['public_enablement'] is False, 'unexpected public enablement')
    qualification = manifest['qualification']
    require(qualification == {'controller': 'bbrv3', 'scenarios': list(SCENARIOS), 'roles': list(ROLES), 'planned_observations': 6,
                             'role_context_seconds': 30, 'test_timeout_seconds': 90, 'driver_timeout_seconds': 120,
                             'container_timeout_seconds': 150, 'zero_evidence': 'separate mandatory hosted R17 job'}, 'existing inventory/bounds differ')
    for name, digest in manifest['bundle_files'].items():
        if (args.bundle / name).exists():
            require(sha((args.bundle / name).read_bytes()) == digest, 'copied bundle helper differs: ' + name)
    wrapper_values, wrapper_detail, charge = receipts(args)
    output = {'audit_pin': full_pin, 'runtime_source': candidate, 'selected_Go_module_equivalence': SELECTED,
              'frozen_runner_sha256': DRIVER_HASH, 'checks': 'passed', 'qualification_complete': False,
              'wrapper_receipts': wrapper_detail, 'charge': charge, 'cases': []}
    build_path = args.bundle / 'build-receipt.json'
    if not build_path.exists() or read(build_path).get('exit_code') != 0:
        output['incomplete_reason'] = 'No successful overlay build receipt; setup charges preserved.'
        return output
    build = read(build_path)
    require(build['product_sha'] == candidate and build['manifest_sha256'] == sha((args.bundle / 'manifest.json').read_bytes()), 'build/source/manifest mismatch')
    require(build['public_enablement'] is False and build['environment'] == manifest['build_environment'], 'build environment or enablement differs')
    require(build['go_version'] == 'go version go1.27.4 linux/amd64', 'wrong build toolchain')
    image = normalized_image((args.bundle / 'image-id.txt').read_text().strip())
    inspection = one_inspection(args.bundle / 'image-inspect.json')
    require(normalized_image(inspection['Id']) == image and inspection['Architecture'] == 'amd64', 'image inspection differs')
    require(build['identity'] == {'QGF_SOURCE_COMMIT': candidate, 'QGF_SOURCE_TREE': manifest['product_tree'], 'QGF_IMAGE_ID': image}, 'build image identity differs')
    require(build['command'] == ['go', 'test', '-overlay=/bundle/overlay.json', '-tags', 'picoquic', '-c', '-o', '/bundle/peer-matrix.test', '.'] and build['working_directory'] == '/product', 'overlay build invocation differs')
    if (args.bundle / 'peer-matrix.test').exists():
        require(sha((args.bundle / 'peer-matrix.test').read_bytes()) == build['binary_sha256'], 'copied test binary differs')
    identity = None
    completed_paths = set()
    for scenario in SCENARIOS:
        for role in ROLES:
            directory = args.results / scenario / role
            if not (directory / 'result.json').exists():
                continue
            case = f'TestPicoquicMultipathMatrix/{scenario}/{role}'
            result, attempt = read(directory / 'result.json'), read(directory / 'attempt.json')
            require(result['status'] == 'pass' and result['executed'] == attempt['expected'] == [case], 'case result/attempt inventory mismatch')
            require(result['controller'] == attempt['controller'] == 'bbrv3', 'case controller differs')
            command, expected = driver.matrix_invocation(scenario, role, '/bundle/peer-matrix.test')
            require(result['command'] == attempt['command'] == command and expected == [case], 'case command differs')
            require(result['started'] == attempt['started'] and result['identity'] == attempt['identity'], 'attempt/result identity differs')
            require(math.isfinite(result['duration_seconds']) and result['duration_seconds'] >= 0, 'invalid case duration')
            current = result['identity']
            if identity is None:
                identity = current
            require(current == identity, 'six-case identity changed')
            require(current['candidate'] == candidate and current['tree'] == manifest['product_tree'] and current['image'] == image, 'case source/image mismatch')
            require(current['go'] == build['go_version'] and current['kernel']['system'] == 'Linux' and current['kernel']['machine'] in ('x86_64', 'amd64'), 'case platform mismatch')
            require(current['picoquic'] == 'fbd46d9a1f54ebf9397f2ee6355b5019ab379fb7' and current['picotls'] == 'e446233b4100ebcdec60901c05bfb7f4cd369c5d', 'peer source pins changed')
            require(current['test_binary_sha256'] == build['binary_sha256'] and current['peer_binary_sha256'] == build['peer_binary_sha256'], 'case binary mismatch')
            require(current['runner_sha256'] == DRIVER_HASH and current['peer_driver_sha256'] == PEER_HASH, 'case driver mismatch')
            log_path = directory / 'go-test.jsonl'
            raw_lines = log_path.read_text().splitlines()
            driver.check_cases(raw_lines, driver.SMOKE_PACKAGE, [case])
            completed_paths.add(log_path)
            events = [json.loads(line) for line in raw_lines]
            text = ''.join(event.get('Output', '') for event in events if event.get('Test') == case)
            peer_paths = re.findall(r'retained peer evidence: (\S+)', text)
            require(len(peer_paths) == 1, 'missing/duplicate retained peer evidence')
            peer_dir = directory / Path(peer_paths[0]).name
            require(peer_dir.name.startswith('matrix-' + role + '-') and (peer_dir / 'peer.log').is_file(), 'peer evidence directory/log missing')
            traffic = re.findall(r'path ([012]) sent (\{[^\n]+)', text)
            require(sorted(path for path, _ in traffic) == ['0', '1', '2'], 'bounded path trace log missing')
            replay = re.findall(r'replayed \d+-byte packet disposition: [^\n]+; retired PATH_ACK\(1\) observed', text)
            if scenario == 'abandon-reopen-late-feedback':
                require(len(replay) == 1, 'late feedback trace witness missing')
            container = one_inspection(args.results / scenario / (role + '.container-inspect.json'))
            require(container['State']['ExitCode'] == 0 and container['State']['Running'] is False, 'container failed/still running')
            require(normalized_image(container['Image']) == image, 'container image differs')
            container_id = (args.results / scenario / (role + '.container-id.txt')).read_text().strip()
            require(container['Id'] == container_id, 'container inspection/id receipt mismatch')
            wrapper = dict(wrapper_values).get('interop-' + scenario + '-' + role)
            require(wrapper and wrapper['status'] == 'passed' and wrapper['exit_code'] == 0, 'case lacks passing charged wrapper')
            require(Decimal(str(result['duration_seconds'])) <= Decimal(wrapper['elapsed_host_seconds']), 'inner case duration exceeds charged wrapper')
            output['cases'].append({'case': case, 'status': result['status'], 'duration_seconds_inner': result['duration_seconds'],
                                    'charged_wrapper_seconds': wrapper['elapsed_host_seconds'], 'peer_evidence_directory': str(peer_dir),
                                    'peer_log_sha256': sha((peer_dir / 'peer.log').read_bytes()),
                                    'path_trace_lines': traffic, 'late_feedback_witness': replay,
                                    'container_id': container_id, 'container_exit_code': container['State']['ExitCode']})
    raw_paths = set(args.results.glob('*/*/go-test.jsonl'))
    if len(output['cases']) == 6:
        require(raw_paths == completed_paths, 'unexpected matrix raw logs')
        require(len(wrapper_values) == 9 and all(receipt['status'] == 'passed' for _, receipt in wrapper_values), 'missing/failed setup, case or aggregate wrapper')
        aggregate = driver.check_matrix(args.results, 'bbrv3')
        require(aggregate == read(args.results / 'matrix-result.json'), 'aggregate differs from original validator')
        output.update(qualification_complete=True, original_matrix_verdict=aggregate)
    else:
        output['incomplete_reason'] = 'Six passing cases and aggregate not yet present; retained attempt charges are preserved.'
    output['identity'] = identity
    output['limitations'] = ['The six existing example-level draft-21 QUIC-v1 scenarios do not replace the separate hosted 16-case Reno and negotiated-zero checks.',
                             'Path traces are bounded original in-test observations, not complete exported qlogs; unchanged source and passing assertions supply the scenario semantics.',
                             'Wrapper occupied time includes setup and container creation/inspection/removal. Inner driver durations are descriptive and are not charged a second time.',
                             'Ordinary-cost qualification and its owner-accepted CPU exception remain separate; this script makes no performance claim.']
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path('/Users/josh/code/github.com/the-sarge/quic-go-fast'))
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--receipts', type=Path, required=True)
    parser.add_argument('--prior-instances', type=int, required=True)
    parser.add_argument('--prior-host-seconds', type=Decimal, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args), indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
