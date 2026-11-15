"""E10 attribution-only scalar/array observer extraction; no operational execution."""
import argparse
import hashlib
import json
from pathlib import Path

MAX_U64 = (1 << 64) - 1
SIZE_UPPER_BOUNDS = [1452, 16384, 20480, 32768, 49152, 65507, None]
NATIVE_REASON_NAMES = ['result_error', 'partial', 'packet_geometry', 'too_small', 'too_large', 'mtu']
RECOVERY_REASON_NAMES = ['handler','shape','local_state','qlog','handshake','amplification','lost_queue','rich_controller','unexpected_bbr_ecn','pto','physical_prefix','pending_ecn','ecn_constraints','ecn_tracker','token_owner','token_level','token_outcome','token_acked','token_early_ack','token_order','token_time','packet_state','history_identity','rich_size','rich_timing','rich_ordinal','rich_delivery','rich_delivery_ordinal','rich_generation','rich_recovery','rich_recovery_ordinal','rich_recovery_state','rich_registration']
OBSERVER_SOURCE = '738ead192547bc107b7b0c142cdd8b7a0146a205'
FIRST_NS, LAST_NS = 17_000_000_000, 73_000_000_000


def require(condition, message):
    if not condition:
        raise ValueError(message)


def uint(value, label):
    require(type(value) is int and 0 <= value <= MAX_U64, f'{label}: expected uint64')
    return value


def count(value, label):
    require(set(value) == {'members', 'packets'}, f'{label}: unexpected count schema')
    return {k:uint(value[k], label+'.'+k) for k in ('members','packets')}


def sums(values):
    return {key:sum(x[key] for x in values) for key in ('members','packets')}


def plus(a,b):
    return {key:a[key]+b[key] for key in ('members','packets')}


def minus(a,b):
    return {key:a[key]-b[key] for key in ('members','packets')}


def fraction(a,b):
    return a/b if b else None


def counter_delta(low, high, label='counters'):
    require(type(low) is type(high), label+': changed schema')
    if isinstance(low,dict):
        require(low.keys()==high.keys(),label+': changed keys')
        return {k:counter_delta(low[k],high[k],label+'.'+k) for k in low}
    if isinstance(low,list):
        require(len(low)==len(high),label+': changed array length')
        return [counter_delta(a,b,f'{label}[{i}]') for i,(a,b) in enumerate(zip(low,high))]
    uint(low,label);uint(high,label)
    require(high>=low,label+': counter regression/wrap')
    return high-low


def validate_native(n,label):
    require(set(n)=={'attempts','seam_attempts','successes','declines','datagrams','recovery'},label+': native schema')
    for k in ('attempts','seam_attempts','successes'):count(n[k],label+'.'+k)
    uint(n['datagrams'],label+'.datagrams')
    require(len(n['declines'])==6,label+': native reason count')
    for i,v in enumerate(n['declines']):count(v,f'{label}.declines[{i}]')
    require(n['attempts']==plus(n['seam_attempts'],sums(n['declines'])),label+': native attempts do not conserve')
    r=n['recovery']
    require(set(r)=={'attempts','rich_attempts','successes','rich_successes','declines'},label+': recovery schema')
    for k in ('attempts','rich_attempts','successes','rich_successes'):count(r[k],label+'.recovery.'+k)
    require(len(r['declines'])==33,label+': recovery reason count')
    for i,v in enumerate(r['declines']):count(v,f'{label}.recovery.declines[{i}]')
    require(n['seam_attempts']==r['attempts'],label+': native/recovery denominator mismatch')
    require(n['successes']==r['successes'],label+': native/recovery success mismatch')
    require(r['attempts']==plus(r['successes'],sums(r['declines'])),label+': recovery attempts do not conserve')
    require(r['rich_attempts']==plus(r['rich_successes'],sums(r['declines'][23:])),label+': rich attempts do not conserve')
    nonrich=minus(r['successes'],r['rich_successes'])
    require(all(v>=0 for v in nonrich.values()),label+': rich successes exceed all successes')
    require(minus(r['attempts'],sums(r['declines'][:23]))==plus(r['rich_attempts'],nonrich),label+': common-stage survival mismatch')
    for k in ('seam_attempts','successes'):
        c=n[k]
        require(2*c['members']<=c['packets']<=64*c['members'],label+'.'+k+': invalid native member packet bounds')


def validate_geometry(g,label):
    require(set(g)=={'handoffs','bytes','datagrams','gso_handoffs','scalar_handoffs','size_buckets'},label+': geometry schema')
    for k,v in g.items():
        if k!='size_buckets':uint(v,label+'.'+k)
    require(len(g['size_buckets'])==7,label+': geometry bucket count')
    for i,v in enumerate(g['size_buckets']):uint(v,f'{label}.size_buckets[{i}]')
    require(sum(g['size_buckets'])==g['handoffs'],label+': geometry bins do not conserve')
    require(g['gso_handoffs']+g['scalar_handoffs']==g['handoffs'],label+': geometry GSO/scalar counts do not conserve')


def validate_snapshot(s,label):
    require(set(s)=={'mono_ns','unix_ns','geometry','native'},label+': snapshot schema')
    require(type(s['mono_ns']) is int and type(s['unix_ns']) is int,label+': noninteger clock')
    validate_geometry(s['geometry'],label+'.geometry')
    validate_native(s['native'],label+'.native')


def describe(s):
    n,g=s['native'],s['geometry'];r=n['recovery']
    def ratio_counts(a,b):return {k:fraction(a[k],b[k]) for k in ('members','packets')}
    return {'counters':{'geometry':g,'native':n},
      'native_eligible_fraction':ratio_counts(n['seam_attempts'],n['attempts']),
      'native_fast_completion_fraction':ratio_counts(n['successes'],n['attempts']),
      'recovery_success_fraction':ratio_counts(r['successes'],r['attempts']),
      'rich_success_fraction':ratio_counts(r['rich_successes'],r['rich_attempts']),
      'first_native_declines':{name:v for name,v in zip(NATIVE_REASON_NAMES,n['declines'])},
      'first_recovery_declines':{name:v for name,v in zip(RECOVERY_REASON_NAMES,r['declines'])},
      'native_packets_per_attempt':fraction(n['attempts']['packets'],n['attempts']['members']),
      'native_datagrams_per_attempt':fraction(n['datagrams'],n['attempts']['members']),
      'handoff_bytes_mean':fraction(g['bytes'],g['handoffs']),
      'handoff_datagrams_mean':fraction(g['datagrams'],g['handoffs'])}


def observation(value,start,label):
    require(value is not None,label+': missing observation')
    require(set(value)=={'snapshots','snapshot_count','snapshot_overflow','final_before_teardown','final_recorded'},label+': observation schema')
    require(len(value['snapshots'])==128,label+': snapshot capacity changed')
    n=value['snapshot_count']
    require(type(n) is int and 1<=n<=128,label+': invalid snapshot count')
    require(uint(value['snapshot_overflow'],label+'.snapshot_overflow')==0,label+': snapshot truncation')
    require(value['final_recorded'] is True,label+': missing final freeze')
    snapshots=value['snapshots'][:n]; final=value['final_before_teardown']
    for i,s in enumerate(snapshots):validate_snapshot(s,f'{label}.snapshot[{i}]')
    validate_snapshot(final,label+'.final')
    for a,b in zip(snapshots,snapshots[1:]):
        require(b['mono_ns']-a['mono_ns']>=1_000_000_000,label+': cadence violation')
        require(b['unix_ns']>a['unix_ns'],label+': wall time regression')
        counter_delta(a['native'],b['native'],label+'.native')
        counter_delta(a['geometry'],b['geometry'],label+'.geometry')
    require(final['mono_ns']>=snapshots[-1]['mono_ns'],label+': final clock precedes last snapshot')
    counter_delta(snapshots[-1]['native'],final['native'],label+'.final.native')
    counter_delta(snapshots[-1]['geometry'],final['geometry'],label+'.final.geometry')
    inside=[s for s in snapshots if FIRST_NS<=s['unix_ns']-start<=LAST_NS]
    return {'label':label,'snapshot_count':n,'snapshot_overflow':0,'final_recorded':True,'lifetime_before_teardown':describe(final),'interior_available_snapshots':inside}


def matching_interior(roles,start):
    all_selected=[r['interior_available_snapshots'] for r in roles.values()]
    if any(len(x)<2 for x in all_selected):
        return {'available':False,'reason':'Fewer than two interior snapshots for at least one role.'}
    lower=max(x[0]['unix_ns'] for x in all_selected);upper=min(x[-1]['unix_ns'] for x in all_selected)
    result={'available':True,'common_nominal_bounds_seconds_after_attempt_start':[(lower-start)/1e9,(upper-start)/1e9],'roles':{}}
    for role,value in roles.items():
        selected=[s for s in value['interior_available_snapshots'] if lower<=s['unix_ns']<=upper]
        if len(selected)<2:
            return {'available':False,'reason':'Fewer than two snapshots in role overlap.'}
        first,last=selected[0],selected[-1]
        delta={'native':counter_delta(first['native'],last['native']), 'geometry':counter_delta(first['geometry'],last['geometry'])}
        validate_native(delta['native'],role+'.delta.native');validate_geometry(delta['geometry'],role+'.delta.geometry')
        result['roles'][role]={'samples':len(selected),'first_mono_ns':first['mono_ns'],'last_mono_ns':last['mono_ns'],'first_unix_ns':first['unix_ns'],'last_unix_ns':last['unix_ns'],'first_seconds_after_attempt_start':(first['unix_ns']-start)/1e9,'last_seconds_after_attempt_start':(last['unix_ns']-start)/1e9,'span_seconds':(last['mono_ns']-first['mono_ns'])/1e9,'adjacent_snapshot_gaps_s':[(b['mono_ns']-a['mono_ns'])/1e9 for a,b in zip(selected,selected[1:])],'observation':describe(delta)}
    return result


def analyze(summary):
    out={'observer_source_schema_pin':OBSERVER_SOURCE,'qualification':False,'timing_acceptance_eligible':False,'size_bucket_upper_bounds_bytes':SIZE_UPPER_BOUNDS,'boundaries':'Lifetime counters freeze before teardown and include startup/warmup. Interior snapshots lie within 17–73 seconds after attempt registration, approximately inside the 5-second setup +10-second warmup +60-second measurement. Server/client use overlapping role bounds, with each actual selected endpoint and monotonic duration reported. These are neither exact 60-second window counts nor synchronized cross-role snapshots. Whole-role profiles include setup/warmup/cleanup; cumulative samples overlap and are not additive removable time. Instrumentation overhead is not removed.','counter_validation':'All captured snapshots and final copies pass strict uint64/schema, per-stage member/packet conservation and snapshot/counter monotonicity checks; overflow/truncation is rejected. This does not claim a mathematical proof against multiple uint64 wraps between observations.','attempts':[]}
    for a in summary['attempts']:
        require(a['status']=='succeeded','failed observation')
        require(a['controller']=='bbrv3' and a['cpu_profile'] is True,'expected profiled BBR diagnostic')
        require(a['mode']=='diagnostic','unexpected run mode')
        item={k:a.get(k) for k in ('profile','status','occupied_s','foreign_cpu_s','contaminated','started_at_unix_ns')}
        roles={}
        for role,entries in (('server',a['server']['connections']),('client',a['client']['flows'])):
            ordinary=[e for e in entries if e['label']=='ordinary'];require(len(ordinary)==1,'expected one ordinary '+role)
            roles[role]=observation(ordinary[0]['bbr_observation'],a['started_at_unix_ns'],a['profile']+'.'+role)
        item['matching_interior']=matching_interior(roles,a['started_at_unix_ns'])
        for value in roles.values():value.pop('interior_available_snapshots')
        item['roles']=roles;out['attempts'].append(item)
    return out


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_directory',type=Path)
    args=parser.parse_args()
    raw=(args.run_directory/'summary.json').read_bytes()
    out=analyze(json.loads(raw));out['summary_sha256']=hashlib.sha256(raw).hexdigest()
    print(json.dumps(out,indent=2,allow_nan=False))


if __name__=='__main__':main()
