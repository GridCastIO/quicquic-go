import datetime, hashlib, json, pathlib, subprocess
root = pathlib.Path('/tmp/qgf-bbr-cost-1368')
def metadata(p):
    s = p.stat()
    birth = subprocess.check_output(['stat', '--printf=%w', str(p)], text=True).strip()
    out = {'path':str(p),'birth_utc':birth,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns,'size':s.st_size}
    if p.is_file() and (p.suffix == '.test' or p.name.endswith('-native-unit.log')):
        out['sha256'] = hashlib.file_digest(p.open('rb'), 'sha256').hexdigest()
    return out
observations = []
for number in range(1,9):
    prefix = f'e{number:02d}'
    run = prefix + ('-observed' if number in (4,7) else '-timing')
    record = {'experiment':prefix,'source':metadata(root/(prefix+'-source')),'binary':metadata(root/(prefix+'.test')),'first_control_log':metadata(root/run/'stateless-pressure/unregistered/server.log')}
    log = root/(prefix+'-native-unit.log')
    if log.exists(): record['native_unit_log'] = metadata(log)
    observations.append(record)
print(json.dumps({'collection_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'host':'minimax','purpose':'Read-only artifact metadata for retrospective native setup accounting; no build or workload executed.','observations':observations},indent=2))
