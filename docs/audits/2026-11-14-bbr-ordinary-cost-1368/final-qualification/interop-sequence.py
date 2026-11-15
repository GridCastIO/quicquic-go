import json
import subprocess
from pathlib import Path

p = Path('/tmp/qgf-final-1368-a1c9442f1-stage')
last = json.loads((p / 'receipts/interop-build.json').read_text())
assert last['status'] == 'passed'
for scenario in ('useful-transfer', 'abandon-reopen-late-feedback', 'same-id-migration-rebinding'):
    for role in ('client', 'server'):
        cmd = ['bash', str(p / 'commands.sh'), 'interop-case', str(p), str(last['remaining_instances_after']), last['remaining_host_seconds_after'], scenario, role]
        code = subprocess.run(cmd, stdout=subprocess.DEVNULL).returncode
        last = json.loads((p / 'receipts' / f'interop-{scenario}-{role}.json').read_text())
        print(json.dumps({'case': scenario, 'role': role, 'exit': code, 'status': last['status'], 'seconds': last['elapsed_host_seconds'], 'remaining_instances': last['remaining_instances_after'], 'remaining_seconds': last['remaining_host_seconds_after']}), flush=True)
        if code:
            raise SystemExit(code)
cmd = ['bash', str(p / 'commands.sh'), 'interop-aggregate', str(p), str(last['remaining_instances_after']), last['remaining_host_seconds_after']]
code = subprocess.run(cmd, stdout=subprocess.DEVNULL).returncode
last = json.loads((p / 'receipts/interop-aggregate.json').read_text())
print(json.dumps({'aggregate_exit': code, 'status': last['status'], 'seconds': last['elapsed_host_seconds'], 'remaining_instances': last['remaining_instances_after'], 'remaining_seconds': last['remaining_host_seconds_after']}), flush=True)
raise SystemExit(code)
