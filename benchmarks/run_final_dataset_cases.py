#!/usr/bin/env python3
from pathlib import Path
import csv,hashlib,math,os,re,statistics,time
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'results'/'final_validation'/'datasets'; OUT.mkdir(parents=True,exist_ok=True)
PUB=ROOT/'datasets'/'public'; USER=ROOT/'datasets'/'input'; USER.mkdir(parents=True,exist_ok=True)
REPS=int(os.environ.get('DATASET_REPS','15')); MAX=int(os.environ.get('FINAL_NETWORK_DATASET_MAX_BYTES','134217728'))
MASK=b'*'[0]

def stat(ns):
    xs=[x/1e6 for x in ns]; ys=sorted(xs); sd=statistics.stdev(xs) if len(xs)>1 else 0.0
    return {'n':len(xs),'mean_ms':statistics.mean(xs),'median_ms':statistics.median(xs),'p95_ms':ys[min(len(ys)-1,max(0,math.ceil(.95*len(ys))-1))],'sd_ms':sd,'ci95_ms':1.96*sd/math.sqrt(len(xs)) if len(xs)>1 else 0.0}
def merkle(leaves):
    if not leaves:return hashlib.sha256(b'').digest()
    x=leaves[:]
    while len(x)>1:
        if len(x)%2:x.append(x[-1])
        x=[hashlib.sha256(x[i]+x[i+1]).digest() for i in range(0,len(x),2)]
    return x[0]
def bench_blocks(path,label,source,status,max_bytes=None):
    use=min(path.stat().st_size,max_bytes or path.stat().st_size); acq=[]; ver=[]; segments=0; root0=None
    reps=max(5,min(REPS,10))
    for _ in range(reps):
        t=time.perf_counter_ns(); leaves=[]; seen=0
        with path.open('rb') as f:
            while seen<use:
                b=f.read(min(4096,use-seen));
                if not b:break
                leaves.append(hashlib.sha256(b).digest()); seen+=len(b)
        root=merkle(leaves); acq.append(time.perf_counter_ns()-t); segments=len(leaves); root0=root
        t=time.perf_counter_ns(); leaves=[]; seen=0
        with path.open('rb') as f:
            while seen<use:
                b=f.read(min(4096,use-seen));
                if not b:break
                leaves.append(hashlib.sha256(b).digest()); seen+=len(b)
        assert merkle(leaves)==root0; ver.append(time.perf_counter_ns()-t)
    a=stat(acq); v=stat(ver)
    return {'experiment':'V-DATA-BLOCK','dataset':label,'source':source,'bytes':use,'records':'','segments':segments,'pii_fields_detected':'','segment_mode':'4096-byte block','redaction_mode':'integrity-only','reps':a['n'],'acquisition_mean_ms':a['mean_ms'],'acquisition_p95_ms':a['p95_ms'],'masking_mean_ms':'','masking_p95_ms':'','verify_mean_ms':v['mean_ms'],'verify_p95_ms':v['p95_ms'],'throughput_MiB_s':(use/(1024**2))/(a['mean_ms']/1000),'status':status}

rows=[]
# Real CIC-IDS2017 mirror: structured network-flow evidence. If IP columns exist, mask them with length-preserving '*'.
cic=PUB/'CICIDS2017_Friday_DDoS.csv'
if cic.exists():
    raw_rows=[]; byte_count=0; headers=[]
    with cic.open('r',encoding='latin1',errors='replace',newline='') as f:
        reader=csv.reader(f); headers=next(reader); raw_rows.append(headers)
        for row in reader:
            s=(','.join(row)+'\n').encode('utf-8',errors='replace');
            if byte_count+len(s)>MAX: break
            raw_rows.append(row); byte_count+=len(s)
    ipidx=[i for i,h in enumerate(headers) if 'source ip' in h.strip().lower() or 'destination ip' in h.strip().lower() or h.strip().lower() in ('src ip','dst ip')]
    acq=[]; red=[]; ver=[]; masked=0
    for rep in range(REPS):
        t=time.perf_counter_ns(); serial=[(','.join(r)+'\n').encode() for r in raw_rows[1:]]; root=merkle([hashlib.sha256(x).digest() for x in serial]); acq.append(time.perf_counter_ns()-t)
        t=time.perf_counter_ns(); out=[]; mc=0
        for rr in raw_rows[1:]:
            r=list(rr)
            for i in ipidx:
                if i<len(r) and r[i]: mc+=1; r[i]='*'*len(r[i])
            out.append((','.join(r)+'\n').encode())
        _=merkle([hashlib.sha256(x).digest() for x in out]); red.append(time.perf_counter_ns()-t)
        t=time.perf_counter_ns(); ok=True
        if ipidx:
            for orig,maskedrow in zip(raw_rows[1:],out):
                # Structural check: transformed record length is preserved when ASCII IPs are masked.
                if len((','.join(orig)+'\n').encode()) != len(maskedrow): ok=False; break
        _=merkle([hashlib.sha256(x).digest() for x in out]); ver.append(time.perf_counter_ns()-t); assert ok
        if rep==0: masked=mc
    a=stat(acq); r=stat(red); v=stat(ver); size=sum(len(x) for x in serial)
    rows.append({'experiment':'V-DATA-NET','dataset':'CIC-IDS2017 Friday DDoS flow CSV','source':'CIC-IDS2017; pinned GitHub mirror eaa09e58937f90cd2a0c7fbf72d6ace8e251fddd','bytes':size,'records':len(serial),'segments':len(serial),'pii_fields_detected':masked,'segment_mode':'CSV flow record','redaction_mode':'length-preserving IP-field mask' if ipidx else 'integrity-only (mirror lacks IP columns)','reps':REPS,'acquisition_mean_ms':a['mean_ms'],'acquisition_p95_ms':a['p95_ms'],'masking_mean_ms':r['mean_ms'],'masking_p95_ms':r['p95_ms'],'verify_mean_ms':v['mean_ms'],'verify_p95_ms':v['p95_ms'],'throughput_MiB_s':(size/(1024**2))/(r['mean_ms']/1000),'status':'MEASURED_REAL_NETWORK_DATASET'})
# Synthetic EXT4 binary artifact is explicitly labeled synthetic; it is a modality/performance stress workload, not a real case.
ext4=PUB/'seal_synthetic_ext4.img'
if ext4.exists(): rows.append(bench_blocks(ext4,'SEAL synthetic EXT4 forensic image','generated deterministic  workload','MEASURED_SYNTHETIC_BINARY_IMAGE'))
# User-supplied real disk images/artifacts, if present.
for p in sorted(x for x in USER.iterdir() if x.is_file()): rows.append(bench_blocks(p,p.name,'user-supplied forensic artifact','MEASURED_USER_FORENSIC_ARTIFACT',min(p.stat().st_size,536870912)))
if not rows: raise SystemExit('No final-validation datasets found')
with (OUT/'final_dataset_bench.csv').open('w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print('wrote',OUT/'final_dataset_bench.csv',len(rows),'rows')
