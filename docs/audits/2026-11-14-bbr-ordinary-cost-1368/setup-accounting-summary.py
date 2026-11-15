import calendar, datetime, decimal, hashlib, json, pathlib, subprocess
D=decimal.Decimal
repo='/Users/josh/code/github.com/the-sarge/quic-go-fast'
pin='993324b2bab871ff544517e6d3542508d3346c4b'
base='docs/audits/2026-11-14-bbr-ordinary-cost-1368/'
def gitbytes(path): return subprocess.check_output(['git','-C',repo,'show',pin+':'+path])
def birth_ns(text):
    date,clock,zone=text.split()
    assert zone=='+0000'
    hms,fraction=clock.split('.')
    stamp=calendar.timegm(datetime.datetime.strptime(date+' '+hms,'%Y-%m-%d %H:%M:%S').timetuple())
    return stamp*1000000000+int(fraction.ljust(9,'0'))
raw=json.loads(pathlib.Path('/tmp/qgf-1368-setup-metadata.json').read_text())
rows=[]
for x in raw['observations']:
    name=x['experiment']; manifest=json.loads(gitbytes(base+name+'-source.json'))
    start=birth_ns(x['source']['birth_utc'])
    end=x.get('native_unit_log',x['binary'])['ctime_ns']
    seconds=D(end-start)/D(1000000000)
    row={'experiment':name,'source':manifest['source'],'binary_sha256':x['binary']['sha256'],'binary_matches_pinned_manifest':x['binary']['sha256']==manifest['binary_sha256'],'start_basis':'source-directory filesystem birth','start_utc':x['source']['birth_utc'],'end_basis':'final native-unit log ctime' if 'native_unit_log' in x else 'binary final ctime','artifact_interval_seconds':str(seconds),'rounded_up_artifact_interval_seconds':str(seconds.to_integral_value(rounding=decimal.ROUND_CEILING)),'first_control_log_birth_utc':x['first_control_log']['birth_utc'],'setup_artifact_precedes_first_control_log':end<birth_ns(x['first_control_log']['birth_utc'])}
    if 'native_unit_log' in x:
        row['native_unit_log_matches_pinned_receipt']=x['native_unit_log']['sha256']==hashlib.sha256(gitbytes(base+name+'-native-unit.log')).hexdigest()
    rows.append(row)
total=sum(D(x['artifact_interval_seconds']) for x in rows)
rounded=sum(D(x['rounded_up_artifact_interval_seconds']) for x in rows)
result={'source_pin':pin,'remote_metadata_sha256':hashlib.sha256(pathlib.Path('/tmp/qgf-1368-setup-metadata.json').read_bytes()).hexdigest(),'rows':rows,'sum_artifact_interval_seconds':str(total),'sum_per_build_ceil_seconds':str(rounded),'accounting_instances':0,'interpretation':'Artifact-envelope reconstruction, not an original monotonic occupied-host measurement. Eight distinct native builds; last three envelopes include native unit checks. Source creation precedes the binary and final test artifact; all precede first observation. Build ordering must be corroborated by original invocation. Rounding up each recovered span is an explicitly conservative accounting estimate, not a strict proven upper bound on unrecorded post-write command cleanup.','excluded':'Repeated same-binary timing and profile runs add no duplicate build setup. Quiet waiting holds no fixture and is excluded under frozen B5 precedent. No new workload was launched.','recorded_before_setup_correction':{'instances':241,'host_seconds':'10709.552619184451','remaining_instances':179,'remaining_host_seconds':'18090.447380815549'},'if_per_build_ceil_adopted':{'instances':241,'host_seconds':str(D('10709.552619184451')+rounded),'remaining_instances':179,'remaining_host_seconds':str(D('18090.447380815549')-rounded)}}
print(json.dumps(result,indent=2))
