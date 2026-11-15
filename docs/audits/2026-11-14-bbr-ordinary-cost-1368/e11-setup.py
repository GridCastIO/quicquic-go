import datetime,hashlib,json,pathlib,re,subprocess,sys,time
base=pathlib.Path('/tmp/qgf-bbr-cost-1368')
source=base/'e11-source'
receipt=base/'e11-setup.json'
if receipt.exists() or source.exists(): raise RuntimeError('E11 setup already exists')
if len(sys.argv) != 2 or not re.fullmatch(r'[0-9a-f]{40}', sys.argv[1]): raise ValueError('full source SHA required')
r={'source':sys.argv[1],'instances':0,'commands':[],'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
start=time.monotonic_ns()
try:
    source.mkdir()
    commands=[['tar','-xzf','/tmp/qgf-bbr-cost-1368-e11.tar.gz','-C',str(source)],['go','test','-c','-tags','ordinarycost','-o',str(base/'e11.test'),'.'],[str(base/'e11.test'),'-test.run','Test(NativeOrdinaryAccepted|NativeOrdinaryBBR|BBRNative|BBRUnregisteredCredit|LocalSendCredit|OrdinaryCostController)','-test.v'],['go','test','./internal/ackhandler','-run','Test(LocalBBR|LocalRenoMemberStill|LocalAcceptedSpan)','-count=1','-v']]
    with (base/'e11-native-unit.log').open('x') as log:
        for cmd in commands:
            r['commands'].append(cmd)
            subprocess.run(cmd,cwd=source,stdout=log,stderr=subprocess.STDOUT,check=True)
    r['result']='passed'
    r['environment']=json.loads(subprocess.check_output(['go','env','-json','GOVERSION','GOOS','GOARCH','GOAMD64','CGO_ENABLED','GOFLAGS','GOEXPERIMENT'],cwd=source))
    r['binary_sha256']=hashlib.sha256((base/'e11.test').read_bytes()).hexdigest()
    r['archive_sha256']=hashlib.sha256(pathlib.Path('/tmp/qgf-bbr-cost-1368-e11.tar.gz').read_bytes()).hexdigest()
except BaseException as error:
    r['result']='failed';r['error']=repr(error);raise
finally:
    r['elapsed_host_seconds']=(time.monotonic_ns()-start)/1e9
    r['ended_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    receipt.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(r),flush=True)
