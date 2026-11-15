import datetime, hashlib, json, os, shlex, subprocess, sys, time
from pathlib import Path
ROOT=Path('/Volumes/worktrees/bbr-final-checks-1368/quic-go-fast')
OUT=Path('/tmp/qgf-final-local-cert-1368')
HEAD='a1c9442f110cca36cb4752b39ce24ae998d76f05'
REFERENCE='59ca2a3a3d6dc9419f9bd09ae4b1e6197153e103'
results=[]
def save():
    (OUT/'commands.json').write_text(json.dumps(results,indent=2)+'\n')
def run(label,argv,extra_env=None):
    env=os.environ.copy()
    if extra_env:env.update(extra_env)
    logfile=OUT/(label+'.log')
    print('BEGIN '+label,flush=True)
    started=datetime.datetime.now(datetime.timezone.utc).isoformat()
    begin=time.monotonic()
    with logfile.open('wb') as stream:
        completed=subprocess.run(argv,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT)
    entry={'label':label,'argv':argv,'environment_overrides':extra_env or {},'command':shlex.join(argv),'cwd':str(ROOT),'source':HEAD,'started_utc':started,'elapsed_seconds':time.monotonic()-begin,'exit_code':completed.returncode,'output':str(logfile),'output_sha256':hashlib.sha256(logfile.read_bytes()).hexdigest()}
    results.append(entry);save()
    print(('PASS ' if completed.returncode==0 else 'FAIL ')+label+' '+str(round(entry['elapsed_seconds'],3))+'s',flush=True)
    if completed.returncode:
        print(logfile.read_text(errors='replace')[-12000:],flush=True)
        raise SystemExit(completed.returncode)
    return logfile.read_text(errors='replace')
assert Path.cwd()==ROOT
run('01-source-head',['git','rev-parse','HEAD'])
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()==HEAD
status=run('02-source-status',['git','status','--porcelain=v1','--branch'])
assert status.strip()=='## codex/bbr-final-checks-1368',status
run('03-go-identity',['git','diff','--exit-code',REFERENCE,HEAD,'--','*.go'])
run('04-module-identity',['git','diff','--exit-code',REFERENCE,HEAD,'--','go.mod','go.sum'])
run('05-toolchain',['go','version'])
run('06-go-environment',['go','env','-json','GOOS','GOARCH','CGO_ENABLED','GOVERSION','GOTOOLCHAIN'])
paths=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
manifest=[]
for path in sorted(x for x in paths if x.endswith('.go') or x in ['go.mod','go.sum','AGENTS.md','docs/agents/domain.md','docs/agents/conventions.md']):
    data=(ROOT/path).read_bytes()
    manifest.append({'path':path,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
(OUT/'source-manifest.json').write_text(json.dumps({'head':HEAD,'go_identical_reference':REFERENCE,'files':manifest},indent=2)+'\n')
run('07-full-affected',['go','test','.','./internal/ackhandler','./internal/congestion','-count=1'])
run('08-focused-race',['go','test','-race','.','./internal/ackhandler','-run','TestLocalBBR|TestLocalAcceptedSpan|TestLocalSendCredit|TestBBRNative|TestBBRUnregisteredCredit|TestNativeProtectionCoalesced|TestNativeOrdinary(Accepted|BBRAccepted)','-count=1'])
run('09-vet',['go','vet','.','./internal/ackhandler','./internal/congestion'])
run('10-tidy',['go','mod','tidy','-diff'])
binaries=[]
for system in ['linux','freebsd','windows']:
    binary=OUT/('quic-final-'+system+'.test')
    run('11-compile-'+system,['go','test','-c','-o',str(binary),'.'],{'GOOS':system,'GOARCH':'amd64'})
    binaries.append({'path':str(binary),'sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'bytes':binary.stat().st_size})
run('12-final-head',['git','rev-parse','HEAD'])
status=run('13-final-status',['git','status','--porcelain=v1','--branch'])
assert status.strip()=='## codex/bbr-final-checks-1368',status
run('14-diff-check',['git','diff','--check'])
receipt={'source':HEAD,'reference':REFERENCE,'worktree':str(ROOT),'branch':'codex/bbr-final-checks-1368','result':'all checks passed','checks':results,'source_manifest_sha256':hashlib.sha256((OUT/'source-manifest.json').read_bytes()).hexdigest(),'binaries':binaries,'scope':'Local certification of retained E09 plus deterministic skip fixture correction. No repository edits or commits and no remote, hosted, or Minimax workload.'}
(OUT/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print('COMPLETE '+str(OUT/'receipt.json'),flush=True)
