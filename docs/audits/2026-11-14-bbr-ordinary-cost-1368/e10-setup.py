import datetime,hashlib,json,pathlib,re,subprocess,sys,time
base=pathlib.Path('/tmp/qgf-bbr-cost-1368')
source=base/'e10-source'
receipt=base/'e10-setup.json'
if receipt.exists() or source.exists(): raise RuntimeError('E10 setup already exists')
if len(sys.argv) != 2 or not re.fullmatch(r'[0-9a-f]{40}', sys.argv[1]): raise ValueError('full source SHA required')
r={'source':sys.argv[1],'instances':0,'commands':[],'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
start=time.monotonic_ns()
try:
    source.mkdir()
    commands=[['tar','-xzf','/tmp/qgf-bbr-cost-1368-e10.tar.gz','-C',str(source)],['go','test','-c','-tags','ordinarycost','-o',str(base/'e10.test'),'.'],[str(base/'e10.test'),'-test.run','Test(E10|NativeOrdinaryAccepted|NativeOrdinaryBBRAccepted|OrdinaryCostController)','-test.v'],['go','test','./internal/ackhandler','-run','Test(E10|LocalBBRAcceptedMember|LocalAcceptedSpan)','-count=1','-v']]
    with (base/'e10-native-unit.log').open('x') as log:
        for cmd in commands:
            r['commands'].append(cmd)
            subprocess.run(cmd,cwd=source,stdout=log,stderr=subprocess.STDOUT,check=True)
    r['result']='passed'
    r['environment']=json.loads(subprocess.check_output(['go','env','-json','GOVERSION','GOOS','GOARCH','GOAMD64','CGO_ENABLED','GOFLAGS','GOEXPERIMENT'],cwd=source))
    r['binary_sha256']=hashlib.sha256((base/'e10.test').read_bytes()).hexdigest()
    r['archive_sha256']=hashlib.sha256(pathlib.Path('/tmp/qgf-bbr-cost-1368-e10.tar.gz').read_bytes()).hexdigest()
except BaseException as error:
    r['result']='failed';r['error']=repr(error);raise
finally:
    r['elapsed_host_seconds']=(time.monotonic_ns()-start)/1e9
    r['ended_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    receipt.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(r),flush=True)
