#!/usr/bin/env python3
"""Finite issue #1410 experiment; compiled binaries are pinned by sibling .sha files."""
import ctypes
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time

root = Path(sys.argv[1]).resolve()
variants = ['baseline', 'chunks1000', 'chunks4096']
env = dict(os.environ, GOMAXPROCS='1', GOGC='100', GOMEMLIMIT='off')
lib = ctypes.CDLL('/usr/lib/libSystem.B.dylib')
lib.mach_host_self.restype = ctypes.c_uint
lib.host_processor_info.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.POINTER(ctypes.c_int)), ctypes.POINTER(ctypes.c_uint)]
lib.vm_deallocate.argtypes = [ctypes.c_uint, ctypes.c_size_t, ctypes.c_size_t]
cpu_tree = plistlib.loads(subprocess.check_output(['ioreg', '-a', '-l', '-p', 'IODeviceTree', '-r', '-n', 'cpus']))
clusters = {v['logical-cpu-id']: v['cluster-type'].decode().strip('\0') for v in cpu_tree[0]['IORegistryEntryChildren']}

def ticks():
    count, size = ctypes.c_uint(), ctypes.c_uint()
    info = ctypes.POINTER(ctypes.c_int)()
    result = lib.host_processor_info(lib.mach_host_self(), 2, ctypes.byref(count), ctypes.byref(info), ctypes.byref(size))
    if result:
        raise RuntimeError(f'host_processor_info: {result}')
    values = [list(info[4*i:4*i+4]) for i in range(count.value)]
    lib.vm_deallocate(ctypes.c_uint.in_dll(lib, 'mach_task_self_').value, ctypes.cast(info, ctypes.c_void_p).value, size.value*ctypes.sizeof(ctypes.c_int))
    return values

def activity(before, after):
    out = []
    for i, (a, b) in enumerate(zip(before, after)):
        d = [y-x for x,y in zip(a,b)]
        out.append({'cpu': i, 'cluster': clusters[i], 'busy_percent': round(100*(sum(d)-d[2])/sum(d),2) if sum(d) else 0})
    return out

metadata = {'variants': {v:(root/f'{v}.sha').read_text().strip() for v in variants}, 'go':subprocess.check_output(['go','version'],text=True).strip(), 'host':subprocess.check_output(['sysctl','-n','machdep.cpu.brand_string'],text=True).strip(), 'os':subprocess.check_output(['sw_vers'],text=True), 'clusters':clusters, 'environment':{k:env[k] for k in ['GOMAXPROCS','GOGC','GOMEMLIMIT']}, 'samples':10, 'benchtime':'200ms', 'note':'Per-core Mach CPU ticks; cluster identities from IORegistry. Includes benchmark CPU usage. No CPU pinning or frequency telemetry.'}
(root/'environment.json').write_text(json.dumps(metadata,indent=2)+'\n')
# Rotating order avoids consistently giving any one variant the first position.
with (root/'load.jsonl').open('w') as load:
    for sample in range(10):
        order = variants[sample%3:]+variants[:sample%3]
        for variant in order:
            cmd=[str(root/f'{variant}.test'),'-test.run=^$','-test.bench=^BenchmarkFrameSorter','-test.benchtime=200ms','-test.cpu=1','-test.count=1']
            before=ticks();start=time.time()
            with (root/f'{variant}-{sample:02}.bench').open('w') as output:
                subprocess.run(cmd,env=env,stdout=output,stderr=subprocess.STDOUT,check=True)
            after=ticks()
            load.write(json.dumps({'sample':sample,'variant':variant,'start_unix':start,'duration_seconds':time.time()-start,'cores':activity(before,after)})+'\n');load.flush()
        print(f'timing sample {sample+1}/10 complete',flush=True)
for variant in variants:
    with (root/f'{variant}.bench').open('w') as output:
        for sample in range(10): output.write((root/f'{variant}-{sample:02}.bench').read_text())
# Separate subprocess per retained-memory cell, keeping timing and GC probes apart.
with (root/'retained.jsonl').open('w') as output:
    for variant in variants:
        for gaps in [10,1000,4096]:
            if variant != 'chunks4096' and gaps>1000: continue
            for phase in [False,True]:
                for stage in ['fragmented','partial','drained','discarded']:
                    cell=dict(env,SORTER_HEAP_GAPS=str(gaps),SORTER_HEAP_PHASE=str(phase).lower(),SORTER_HEAP_STAGE=stage)
                    raw=subprocess.check_output([str(root/f'{variant}.test'),'-test.run=^TestFrameSorterRetainedHeap$','-test.count=1'],env=cell,text=True)
                    report=json.loads(next(line for line in raw.splitlines() if line.startswith('{')))
                    output.write(json.dumps(dict(report,variant=variant))+'\n');output.flush()
    print('retained-memory cells complete',flush=True)
