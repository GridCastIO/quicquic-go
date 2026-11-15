import argparse,hashlib,json,pathlib,subprocess
p=argparse.ArgumentParser();p.add_argument('--binary',type=pathlib.Path,required=True);p.add_argument('--results',type=pathlib.Path,required=True);a=p.parse_args()
out=a.results/'profile-analysis';out.mkdir(exist_ok=False)
r={'binary_sha256':hashlib.sha256(a.binary.read_bytes()).hexdigest(),'commands':[],'boundary':'Whole role CPU profile including setup/warmup/teardown. Cumulative functions overlap; not additive savings or matching-window CPU.'}
try:
 for profile in ('unregistered','opted-in'):
  for role in ('server','client'):
   raw=a.results/'stateless-pressure'/profile/(role+'.cpu.pprof')
   for mode in ('flat','cum'):
    cmd=['go','tool','pprof','-top','-nodefraction=0','-nodecount=180']
    if mode=='cum':cmd.append('-cum')
    cmd.extend([str(a.binary),str(raw)])
    output=profile+'-'+role+'-'+mode+'.txt'
    result=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (out/output).write_text(result.stdout)
    r['commands'].append({'profile':profile,'role':role,'profile_sha256':hashlib.sha256(raw.read_bytes()).hexdigest(),'command':cmd,'exit':result.returncode,'output':output})
    if result.returncode:raise RuntimeError(output+' failed')
finally:
 (out/'commands.json').write_text(json.dumps(r,indent=2)+'\n')
print(str(out))
