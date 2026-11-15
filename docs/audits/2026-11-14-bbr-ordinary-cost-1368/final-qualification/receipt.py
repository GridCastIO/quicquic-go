#!/usr/bin/env python3
"""Record one setup or interop attempt; ordinary timing uses its frozen ledger."""
import argparse
import datetime
from decimal import Decimal
import json
import os
from pathlib import Path
import signal
import subprocess
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--receipt', type=Path, required=True)
p.add_argument('--instances', type=int, choices=(0, 1), required=True)
p.add_argument('--remaining-instances', type=int, required=True)
p.add_argument('--remaining-host-seconds', type=Decimal, required=True)
p.add_argument('--reserve-host-seconds', type=Decimal, default=Decimal(0))
p.add_argument('command', nargs=argparse.REMAINDER)
a = p.parse_args()
command = a.command[1:] if a.command[:1] == ['--'] else a.command
if not command or a.remaining_instances < a.instances or a.remaining_host_seconds < a.reserve_host_seconds:
    p.error('missing command or insufficient caller-supplied remaining allowance')
a.receipt.parent.mkdir(parents=True, exist_ok=True)
log_path = a.receipt.with_suffix('.log')
if a.receipt.exists() or log_path.exists():
    p.error('preserve existing attempt; use a fresh receipt path')
record = dict(command=command, working_directory=os.getcwd(), instances_charged=a.instances,
              remaining_instances_before=a.remaining_instances,
              remaining_host_seconds_before=str(a.remaining_host_seconds),
              reserved_host_seconds=str(a.reserve_host_seconds), status='started',
              started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
              elapsed_host_seconds=None)
def save():
    temporary = a.receipt.with_suffix('.tmp')
    temporary.write_text(json.dumps(record, indent=2) + '\n')
    temporary.replace(a.receipt)
save()  # Durable pre-launch instance charge; never discard a failed attempt.
started = time.monotonic_ns()
process = None
code = 1
def interrupt(signum, frame):
    raise KeyboardInterrupt(f'signal {signum}')
old = {s: signal.signal(s, interrupt) for s in (signal.SIGINT, signal.SIGTERM)}
try:
    with log_path.open('x') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        code = process.wait()
    record['status'] = 'passed' if code == 0 else 'failed'
except BaseException as error:
    record.update(status='interrupted' if isinstance(error, KeyboardInterrupt) else 'failed', error=f'{type(error).__name__}: {error}')
    code = 130 if isinstance(error, KeyboardInterrupt) else 1
    if process is not None and process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
finally:
    elapsed = Decimal(time.monotonic_ns() - started) / Decimal(1_000_000_000)
    record.update(exit_code=code, elapsed_host_seconds=str(elapsed),
                  ended_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  remaining_instances_after=a.remaining_instances-a.instances,
                  remaining_host_seconds_after=str(a.remaining_host_seconds-elapsed))
    save()
    for sig, handler in old.items():
        signal.signal(sig, handler)
print(json.dumps(record, indent=2))
raise SystemExit(code)
