import copy, importlib.util, json
spec=importlib.util.spec_from_file_location('e10','/tmp/qgf-e10-analyze.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def c(n):return {'members':n,'packets':16*n}
def snap(i,offset=0,zero=False):
 n=0 if zero else i
 native={'attempts':c(100*n),'seam_attempts':c(80*n),'successes':c(60*n),'declines':[c(20*n)]+[c(0) for _ in range(5)],'datagrams':1600*n,'recovery':{'attempts':c(80*n),'rich_attempts':c(60*n),'successes':c(60*n),'rich_successes':c(50*n),'declines':[c(10*n)]+[c(0) for _ in range(22)]+[c(10*n)]+[c(0) for _ in range(9)]}}
 geometry={'handoffs':120*n,'bytes':120000*n,'datagrams':120*n,'gso_handoffs':100*n,'scalar_handoffs':20*n,'size_buckets':[120*n,0,0,0,0,0,0]}
 t=(16+i)*10**9+offset
 return {'mono_ns':t,'unix_ns':t+10**12,'geometry':geometry,'native':native}
def obs(offset=0,zero=False):
 s=[snap(i,offset,zero) for i in range(1,58)]
 return {'snapshots':s+[snap(0,zero=True) for _ in range(128-len(s))],'snapshot_count':len(s),'snapshot_overflow':0,'final_recorded':True,'final_before_teardown':snap(58,offset,zero)}
a={'profile':'opted-in','status':'succeeded','mode':'diagnostic','controller':'bbrv3','cpu_profile':True,'started_at_unix_ns':10**12,'server':{'connections':[{'label':'ordinary','bbr_observation':obs()}]},'client':{'flows':[{'label':'ordinary','bbr_observation':obs(50_000_000)}]}}
summary={'attempts':[a]}
out=m.analyze(summary)
assert out['attempts'][0]['roles']['server']['lifetime_before_teardown']['native_fast_completion_fraction']=={'members':.6,'packets':.6}
assert out['attempts'][0]['matching_interior']['available']
z=copy.deepcopy(summary)
for role,key in (('server','connections'),('client','flows')):z['attempts'][0][role][key][0]['bbr_observation']=obs(zero=True)
assert m.analyze(z)['attempts'][0]['roles']['server']['lifetime_before_teardown']['native_fast_completion_fraction']=={'members':None,'packets':None}
cases={
 'native conservation':lambda o:o['snapshots'][2]['native']['attempts'].__setitem__('packets',0),
 'rich conservation':lambda o:o['snapshots'][2]['native']['recovery']['rich_attempts'].__setitem__('members',0),
 'bin conservation':lambda o:o['snapshots'][2]['geometry']['size_buckets'].__setitem__(0,0),
 'snapshot truncation':lambda o:o.__setitem__('snapshot_overflow',1),
 'missing final':lambda o:o.__setitem__('final_recorded',False),
 'cadence':lambda o:o['snapshots'][2].__setitem__('mono_ns',o['snapshots'][1]['mono_ns']+1),
 'uint64 overflow':lambda o:o['snapshots'][2]['native'].__setitem__('datagrams',1<<64),
 'counter regression':lambda o:o['snapshots'][2].update(geometry=copy.deepcopy(o['snapshots'][0]['geometry']),native=copy.deepcopy(o['snapshots'][0]['native'])),
}
for name,change in cases.items():
 bad=copy.deepcopy(summary);change(bad['attempts'][0]['server']['connections'][0]['bbr_observation'])
 try:m.analyze(bad)
 except ValueError:pass
 else:raise AssertionError('accepted '+name)
print(json.dumps({'valid_nonzero_and_zero_denominators':'passed','rejections':list(cases),'matching_intervals':'passed','status':'passed'},indent=2))
