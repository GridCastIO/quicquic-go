#!/usr/bin/env python3
"""Summarize the finite measurement outputs; benchstat owns significance tests."""
import json
from pathlib import Path
import statistics
import subprocess
import sys

root=Path(sys.argv[1]).resolve()
variants=['baseline','chunks4096','maprelease']
results={}
for variant in variants:
    rows={}
    for line in (root/f'{variant}.bench').read_text().splitlines():
        if not line.startswith('Benchmark'): continue
        parts=line.split()
        values={parts[i+1]:float(parts[i]) for i in range(2,len(parts)-1,2)}
        for metric,value in values.items(): rows.setdefault((parts[0],metric),[]).append(value)
    results[variant]=rows
summary={}
for key in sorted(set().union(*(set(r) for r in results.values()))):
    name,metric=key
    row={}
    for variant in variants:
        if key not in results[variant]:continue
        values=results[variant][key]
        row[variant]={'median':statistics.median(values),'min':min(values),'max':max(values),'samples':len(values)}
        if variant!='baseline' and key in results['baseline']:
            old=results['baseline'][key]
            if statistics.median(old):row[variant]['delta_percent']=100*(statistics.median(values)/statistics.median(old)-1)
            row[variant]['pairs_higher']=sum(b>a for a,b in zip(old,values))
    summary.setdefault(name,{})[metric]=row
(root/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
for fmt,output in [('text','benchstat.log'),('csv','benchstat.csv')]:
    with (root/output).open('w') as f, (root/(output+'.warnings')).open('w') as warnings:
        subprocess.run([str(root/'benchstat'),'-format',fmt,*(f'{v}.bench' for v in variants)],cwd=root,stdout=f,stderr=warnings,check=True)
loads=[json.loads(line) for line in (root/'load.jsonl').read_text().splitlines()]
load_summary={}
for kind in ['E','P']:
    values=[sum(c['busy_percent'] for c in row['cores'] if c['cluster']==kind)/100 for row in loads]
    load_summary[kind]={'min_core_equivalents':min(values),'median_core_equivalents':statistics.median(values),'max_core_equivalents':max(values)}
(root/'load-summary.json').write_text(json.dumps(load_summary,indent=2)+'\n')
for name in ['Construct','Overlap/gaps=10','Overlap/gaps=100','Overlap/gaps=1000','Overlap/gaps=4096']:
    row=summary['BenchmarkFrameSorter'+name]['ns/op']
    print(name, json.dumps(row))
print('LOAD',json.dumps(load_summary))

with (root/'candidate-comparison.log').open('w') as output:
    subprocess.run([str(root/'benchstat'),'chunks4096.bench','maprelease.bench'],cwd=root,stdout=output,check=True)
