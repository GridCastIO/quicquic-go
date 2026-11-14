import json, collections, sys
from pathlib import Path
d = Path(sys.argv[1])
for arm in sys.argv[2].split(","):
    rt = sw = None
    for line in open(d / f"{arm}.trace.json"):
        try: o = json.loads(line)
        except Exception: continue
        if o.get("type") == "map":
            if "@rt" in o["data"]: rt = o["data"]["@rt"]
            if "@sw" in o["data"]: sw = o["data"]["@sw"]
    s = json.load(open(d / f"{arm}.summary.json"))
    comm = collections.Counter(); percpu = collections.Counter(); fixture_cpu = collections.Counter()
    for k, v in rt.items():
        parts = k.split(","); cpu = int(parts[0]); name = ",".join(parts[1:-1])
        if name.startswith("swapper"): continue
        comm[name] += v; percpu[cpu] += v
        if name.startswith("aggregation.te"): fixture_cpu[cpu] += v
    sd = {int(k): v for k, v in s.get("sched_delta_ns", {}).items()}
    def rd(t):
        out = {}
        for l in t.splitlines():
            if l.startswith("cpu") and l[3].isdigit():
                q = l.split(); out[int(q[0][3:])] = list(map(int, q[1:]))
        return out
    a, b = rd(s["stat_before"]), rd(s["stat_after"])
    wall = s["occupied_s"]
    idle_busy = {c: wall - ((b[c][3] - a[c][3]) + (b[c][4] - a[c][4])) / 100 for c in (sd or {c: 0 for c in [4,5]+list(range(8,16))+[20,21]+list(range(24,32))})}
    stat_busy = {c: sum(b[c][i] - a[c][i] for i in (0, 1, 2, 5, 6, 7)) / 100 for c in (sd or {c: 0 for c in [4,5]+list(range(8,16))+[20,21]+list(range(24,32))})}
    print(arm, "rusage", round(sum(s["process_cpu_s"].values()), 2), "foreign", round(s["foreign_cpu_s"], 2),
          "trace nonidle", round(sum(percpu.values()) / 1e9, 2), "schedstat", round(sum(sd.values()) / 1e9, 2), "wall-idle", round(sum(idle_busy.values()), 2), "stat-busy", round(sum(stat_busy.values()), 2))
    for c, v in comm.most_common(8): print("   ", c, round(v / 1e9, 3))
    print("    cpu: schedstat / trace-all / trace-fixture / wall-idle / stat-busy / switches")
    for c in sorted(set(sd) | set(percpu)):
        print(f"    {c:2d} {sd.get(c,0)/1e9:7.2f} {percpu.get(c,0)/1e9:7.2f} {fixture_cpu.get(c,0)/1e9:7.2f} {idle_busy.get(c,0):7.2f} {stat_busy.get(c,0):7.2f} {sw.get(str(c),0) if sw else '-'}")
