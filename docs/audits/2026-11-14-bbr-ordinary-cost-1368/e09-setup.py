import datetime,hashlib,json,pathlib,subprocess,time
base=pathlib.Path('/tmp/qgf-bbr-cost-1368')
source=base/'e09-source'
receipt=base/'e09-setup.json'
if receipt.exists() or source.exists(): raise RuntimeError('E09 setup already exists')
r={'source':'76f64bd9418bcf403c6b0eaecdffc69ca611073c','instances':0,'commands':[],'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
start=time.monotonic_ns()
try:
    source.mkdir()
    commands=[['tar','-xzf','/tmp/qgf-bbr-cost-1368-e09.tar.gz','-C',str(source)],['go','test','-c','-tags','ordinarycost','-o',str(base/'e09.test'),'.'],[str(base/'e09.test'),'-test.run','Test(NativeOrdinaryAccepted|NativeOrdinaryBBRAccepted|BBRNative|BBRUnregisteredCredit|LocalSendCredit|OrdinaryCostController)','-test.v'],['go','test','./internal/ackhandler','-run','TestLocalBBRAcceptedMember','-count=1','-v']]
    with (base/'e09-native-unit.log').open('x') as log:
        for cmd in commands:
            r['commands'].append(cmd)
            subprocess.run(cmd,cwd=source,stdout=log,stderr=subprocess.STDOUT,check=True)
    r['result']='passed'
    r['environment']=json.loads(subprocess.check_output(['go','env','-json','GOVERSION','GOOS','GOARCH','GOAMD64','CGO_ENABLED','GOFLAGS','GOEXPERIMENT'],cwd=source))
    r['binary_sha256']=hashlib.sha256((base/'e09.test').read_bytes()).hexdigest()
    r['archive_sha256']=hashlib.sha256(pathlib.Path('/tmp/qgf-bbr-cost-1368-e09.tar.gz').read_bytes()).hexdigest()
except BaseException as error:
    r['result']='failed';r['error']=repr(error);raise
finally:
    r['elapsed_host_seconds']=(time.monotonic_ns()-start)/1e9
    r['ended_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    receipt.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(r),flush=True)
