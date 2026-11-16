import json, pathlib, subprocess, os
root=pathlib.Path('/Volumes/worktrees/crypto-stream-release-1411')
results=root/'quic-go-fast/docs/audits/crypto-stream-release-1411/results'
env=dict(os.environ,GOMAXPROCS='4')
for trial in range(1,6):
 for kind in (['baseline','candidate'] if trial%2 else ['candidate','baseline']):
  stem=f'{trial}-{kind}'
  p=subprocess.run([str(root/f'heap-{kind}'),'-connections','1000','-profile',str(results/f'{stem}.pprof')],env=env,capture_output=True,text=True,check=True)
  (results/f'{stem}-heap.json').write_text(p.stdout)
  if p.stderr: (results/f'{stem}-heap.stderr').write_text(p.stderr)
  for bench,pattern in [('bench','^BenchmarkCrypto'),('handshake','^BenchmarkHandshake$')]:
   p=subprocess.run([str(root/f'{bench}-{kind}'),'-test.run','^$','-test.bench',pattern,'-test.benchtime','1s','-test.count','1'],env=env,capture_output=True,text=True,check=True,cwd=root/'quic-go-fast')
   (results/f'{stem}-{bench}.txt').write_text(p.stdout)
   if p.stderr: (results/f'{stem}-{bench}.stderr').write_text(p.stderr)
  print(stem, (results/f'{stem}-heap.json').read_text().strip(),flush=True)
