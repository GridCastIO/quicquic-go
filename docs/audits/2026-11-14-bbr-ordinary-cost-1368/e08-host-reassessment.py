import json, os, time
from pathlib import Path
CPUS=list(range(8,16))+list(range(24,32))
HZ=os.sysconf('SC_CLK_TCK')
def cores():
 out={}
 for line in Path('/proc/schedstat').read_text().splitlines():
  if line.startswith('cpu'):
   f=line.split(); out[int(f[0][3:])]=int(f[7])
 return out
def proc():
 out={}
 for p in Path('/proc').iterdir():
  if not p.name.isdigit(): continue
  try:
   raw=(p/'stat').read_text(); left=raw.index('('); right=raw.rindex(')'); f=raw[right+2:].split()
   out[int(p.name)]={'comm':raw[left+1:right],'ticks':int(f[11])+int(f[12]),'rss_bytes':int(f[21])*os.sysconf('SC_PAGE_SIZE'),'state':f[0],'last_cpu':int(f[36]),'threads':int(f[17]),'start_ticks':int(f[19])}
  except (FileNotFoundError,ProcessLookupError,PermissionError,ValueError,IndexError): pass
 return out
def threads(pid):
 out=[]
 try: entries=list(Path(f'/proc/{pid}/task').iterdir())
 except (FileNotFoundError,PermissionError): return out
 for p in entries:
  try:
   raw=(p/'stat').read_text(); right=raw.rindex(')'); f=raw[right+2:].split()
   mask=next((s.split(':',1)[1].strip() for s in (p/'status').read_text().splitlines() if s.startswith('Cpus_allowed_list:')),None)
   out.append({'tid':int(p.name),'comm':raw[raw.index('(')+1:right],'last_cpu':int(f[36]),'ticks':int(f[11])+int(f[12]),'allowed_cpus':mask})
  except (FileNotFoundError,ProcessLookupError,PermissionError,ValueError,IndexError): pass
 return out
def resources():
 keys={'MemAvailable','SwapFree','Dirty','Writeback'}
 mem={s.split(':',1)[0]:s.split(':',1)[1].strip() for s in Path('/proc/meminfo').read_text().splitlines() if s.split(':',1)[0] in keys}
 return {'loadavg':Path('/proc/loadavg').read_text().strip(),'memory':mem,'pressure':{k:Path(f'/proc/pressure/{k}').read_text().strip() for k in ['cpu','memory','io']}}
start=time.monotonic(); p=proc(); c=cores(); at=time.monotonic()
print(json.dumps({'kind':'start','unix_ns':time.time_ns(),'fixture_cpus':CPUS,'sample_seconds':5,'samples':11,'clock_ticks':HZ,'resources':resources()}),flush=True)
for i in range(11):
 time.sleep(5)
 nc=cores(); np=proc(); nat=time.monotonic(); duration=nat-at
 shares={str(cpu):(nc[cpu]-c[cpu])/1e9/duration for cpu in CPUS}
 active=[]
 for pid,v in np.items():
  old=p.get(pid)
  if old and old['start_ticks']==v['start_ticks']:
   delta=(v['ticks']-old['ticks'])/HZ
   if delta>0: active.append(dict(pid=pid,cpu_seconds=delta,cpu_share=delta/duration,**v))
 active.sort(key=lambda v:v['cpu_seconds'],reverse=True)
 for item in active[:8]:
  item.pop('ticks',None);item.pop('start_ticks',None)
  if item['cpu_seconds']>duration*.05: item['thread_snapshot']=threads(item['pid'])
 print(json.dumps({'kind':'sample','sample':i+1,'unix_ns':time.time_ns(),'duration_s':duration,'maximum_core_share':max(shares.values()),'quiet':max(shares.values())<.05,'shares':shares,'processes':active[:8],'resources':resources()}),flush=True)
 p,c,at=np,nc,nat
print(json.dumps({'kind':'end','elapsed_s':time.monotonic()-start}),flush=True)
