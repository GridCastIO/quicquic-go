import decimal,json,pathlib,subprocess,types,math
D=decimal.Decimal
repo='/Users/josh/code/github.com/the-sarge/quic-go-fast'
pin='364bfd49c3f4a5176f1c0678a9693eb5a4ebc8da'
root=pathlib.Path('/Volumes/worktrees/bbr-ordinary-cost-1368/quic-go-fast/docs/audits/2026-11-14-bbr-ordinary-cost-1368')
base=root/'e09-window2-timing'
def pinned(path): return subprocess.check_output(['git','-C',repo,'show',pin+':'+path])
driver=types.ModuleType('pinned_ordinary_cost_audit')
exec(compile(pinned('interop/multipath/ordinary_cost.py'),'pinned_ordinary_cost.py','exec'),driver.__dict__)
read=lambda p: json.loads(p.read_text())
summary,ledger,identity=map(read,[base/'summary.json',base/'ledger.json',base/'identity.json'])
records=[json.loads(x) for x in (base/'diagnostic.jsonl').read_text().splitlines()]
assert len(records)==2 and records==ledger['attempts']==summary['attempts']
manifest=json.loads(pinned('docs/audits/2026-11-14-bbr-ordinary-cost-1368/e09-window2-source.json'))
assert identity['candidate']==manifest['source'] and identity['binary']['sha256']==manifest['binary_sha256']
assert identity['metric_boundaries']==driver.METRIC_BOUNDARIES==summary['metric_boundaries']
assert identity['controller']=='bbrv3' and not identity['cpu_profile'] and identity['mode']=='diagnostic'
assert identity['warmup_s']==10 and identity['window_s']==60
assert identity['server_cpus']=='8-11' and identity['client_cpus']=='12-15'
assert identity['fixture_cpus_and_siblings']==driver.FIXTURE_CPUS
assert identity['remaining_instances']==177 and math.isclose(identity['remaining_host_seconds'],17884.55455536010394)
results=[]
for index,r in enumerate(records):
 assert r['profile']==('unregistered','opted-in')[index] and r['seed']==1038 and r['attempt']==0 and r['round']==0
 assert r['status']=='succeeded' and r['mode']=='diagnostic' and r['candidate']==manifest['source'] and r['controller']=='bbrv3'
 assert not r['cpu_profile'] and r['exit']=={'server':0,'client':0}
 for role in ('server','client'):
  p=base/'stateless-pressure'/r['profile']/(role+'.json')
  assert read(p)==r[role]
  driver.check_role_log(role,p.with_suffix('.log').read_text())
  usage=r[role]['window_rusage']
  assert all(usage['end'][k]-usage['start'][k]==v for k,v in usage['delta'].items())
  cpu=(usage['delta']['user_cpu_ns']+usage['delta']['system_cpu_ns'])/1e9
  assert cpu==r[role]['window_cpu_s']
 driver.check_observation(r)
 flow=driver.flows(r,'ordinary')[0]
 limit=driver.foreign_limit_s(r['occupied_s'])
 assert r['contaminated']==(r['foreign_cpu_s']>limit)
 results.append({'profile':r['profile'],'useful_bytes':flow['useful_bytes'],'goodput_gbit_s':flow['useful_bytes']*8/60/1e9,'server_window_cpu_s':r['server']['window_cpu_s'],'client_window_cpu_s':r['client']['window_cpu_s'],'server_cpu_ns_per_useful_byte':r['server']['window_cpu_s']/driver.useful_bytes(r)*1e9,'foreign_cpu_s':r['foreign_cpu_s'],'foreign_limit_at_charged_occupied_s':limit,'foreign_limit_multiple':r['foreign_cpu_s']/limit,'occupied_s':r['occupied_s'],'rss_kb_at_20s':r['server']['rss_kb_at_20s'],'rss_kb_end':r['server']['rss_kb_end'],'joined':r['server']['joined'],'control_p99_us':flow['control']['p99_us'],'send_p99_us':r['server']['application_send_call']['ordinary']['p99_us'],'flood':r['client']['flood'],'quiet':r['quiet']})
verdict=driver.judge_cell('stateless-pressure',[tuple(records)])
assert verdict==summary['diagnostic']
assert sum(r['occupied_s'] for r in records)==ledger['host_seconds_charged']==summary['host_seconds_charged']
assert ledger['instances_charged']==summary['instances_charged']==2
assert ledger['remaining_instances_supplied']==177 and math.isclose(ledger['remaining_host_seconds_supplied'],17884.55455536010394)
oldpath='docs/audits/2026-11-14-bbr-ordinary-cost-1368/e08-quiet-window-timing/diagnostic.jsonl'
old=[json.loads(x) for x in pinned(oldpath).decode().splitlines()]
comparison=[]
for oldr,new in zip(old,results):
 oldflow=driver.flows(oldr,'ordinary')[0]
 oldgb=oldflow['useful_bytes']*8/60/1e9
 oldcpu=oldr['server']['window_cpu_s']
 oldcpub=oldcpu/driver.useful_bytes(oldr)*1e9
 comparison.append({'profile':new['profile'],'old_goodput_gbit_s':oldgb,'new_goodput_gbit_s':new['goodput_gbit_s'],'goodput_change_pct':100*(new['goodput_gbit_s']/oldgb-1),'old_server_cpu_s':oldcpu,'new_server_cpu_s':new['server_window_cpu_s'],'server_cpu_change_pct':100*(new['server_window_cpu_s']/oldcpu-1),'old_cpu_ns_per_byte':oldcpub,'new_cpu_ns_per_byte':new['server_cpu_ns_per_useful_byte'],'cpu_per_byte_change_pct':100*(new['server_cpu_ns_per_useful_byte']/oldcpub-1),'both_compared_pairs_timing_valid':not any(r['contaminated'] for r in records)})
charge=D(str(ledger['host_seconds_charged']))
out={'source_pin':pin,'runtime_source':manifest['source'],'binary_sha256':manifest['binary_sha256'],'raw_copies_roles_rusage_series_driver_judgment_identity_accounting_checks':'passed','observations':results,'diagnostic':verdict,'timing_valid':not any(r['contaminated'] for r in records),'reason':'Validity follows unchanged contamination and role checks. A valid single diagnostic pair still does not establish repeatability or satisfy final qualification.','comparison_to_E08_valid_pair_descriptive_only':comparison,'charge':{'instances':2,'host_seconds':str(charge),'cumulative_instances':245,'cumulative_host_seconds':str(D('10915.44544463989606')+charge),'remaining_instances':175,'remaining_host_seconds':str(D('17884.55455536010394')-charge)},'limitations':'Foreign CPU is checked against stored driver accounting and source formula; raw schedstat/softirq endpoints are not saved, so it is not reconstructed independently. Foreign limit shown uses slightly longer final ledger occupied time; this tiny interval difference does not affect the clean result. The exact inner occupied interval is not separately saved.'}
print(json.dumps(out,indent=2))
