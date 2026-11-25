#!/usr/bin/env python3
import os, re, time, csv, hashlib, statistics, math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results'/'datasets'; OUT.mkdir(parents=True,exist_ok=True)
PUB=ROOT/'datasets'/'public'; USER=ROOT/'datasets'/'input'
MASK=42
REPS=int(os.environ.get('DATASET_REPS','15'))
MAX_BYTES=int(os.environ.get('FORENSIC_MAX_BYTES',str(512*1024*1024)))
IP_RE=re.compile(rb'(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)')
EMAIL_RE=re.compile(rb'(?i)[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}')

def ms_stats(ns):
    xs=[x/1e6 for x in ns]; xs.sort(); n=len(xs)
    mean=statistics.mean(xs); sd=statistics.stdev(xs) if n>1 else 0.0
    return dict(mean_ms=mean,median_ms=statistics.median(xs),p95_ms=xs[min(n-1,max(0,math.ceil(.95*n)-1))],stdev_ms=sd,ci95_ms=(1.96*sd/math.sqrt(n) if n>1 else 0.0))

def merkle(leaves):
    if not leaves: return hashlib.sha256(b'SEAL-empty-tree').digest()
    n=1
    while n<len(leaves): n*=2
    empty=hashlib.sha256(b'SEAL-empty-leaf').digest(); level=leaves+[empty]*(n-len(leaves))
    while len(level)>1:
        level=[hashlib.sha256(level[i]+level[i+1]).digest() for i in range(0,len(level),2)]
    return level[0]

def mask_line(line):
    out=bytearray(line); spans=[]
    for rx in (IP_RE,EMAIL_RE):
        for m in rx.finditer(line):
            spans.append(m.span())
    # merge overlapping spans
    spans=sorted(spans)
    merged=[]
    for a,b in spans:
        if merged and a<=merged[-1][1]: merged[-1]=(merged[-1][0],max(merged[-1][1],b))
        else: merged.append((a,b))
    for a,b in merged:
        for i in range(a,b): out[i]=MASK
    return bytes(out),merged

def mask_ok(o,r):
    return len(o)==len(r) and all(a==b or b==MASK for a,b in zip(o,r))

def hash_commit(data):
    rho=hashlib.sha256(b'SEAL-dataset-rho'+hashlib.sha256(data).digest()).digest()
    return hashlib.sha256(b'SEAL-COM-v1'+len(data).to_bytes(8,'big')+rho+data).digest()

rows=[]
for path in sorted(PUB.glob('*.log')):
    raw=path.read_bytes(); lines=raw.splitlines(keepends=True)
    acq_t=[]; red_t=[]; ver_t=[]; roots=[]; pii_count=0
    for rep in range(REPS):
        t=time.perf_counter_ns()
        commits=[hash_commit(x) for x in lines]
        root=merkle([hashlib.sha256(x).digest() for x in lines]); roots.append(root)
        acq_t.append(time.perf_counter_ns()-t)
        t=time.perf_counter_ns(); red=[]; pc=0
        for line in lines:
            rr,sp=mask_line(line); red.append(rr); pc += len(sp)
        red_root=merkle([hashlib.sha256(x).digest() for x in red]); _=red_root
        red_t.append(time.perf_counter_ns()-t)
        t=time.perf_counter_ns(); ok=all(mask_ok(o,r) for o,r in zip(lines,red)); _=merkle([hashlib.sha256(x).digest() for x in red]); ver_t.append(time.perf_counter_ns()-t)
        if not ok: raise RuntimeError(f'mask verification failed for {path}')
        if rep==0: pii_count=pc
    a=ms_stats(acq_t); r=ms_stats(red_t); v=ms_stats(ver_t)
    rows.append({'experiment':'C2','dataset':path.name,'source':'Loghub','bytes':len(raw),'records':len(lines),'segments':len(lines),'pii_fields_detected':pii_count,'segment_mode':'line','reps':REPS,
                 'acquisition_mean_ms':a['mean_ms'],'acquisition_p95_ms':a['p95_ms'],'masking_mean_ms':r['mean_ms'],'masking_p95_ms':r['p95_ms'],'verify_mean_ms':v['mean_ms'],'verify_p95_ms':v['p95_ms'],
                 'throughput_MiB_s':(len(raw)/(1024**2))/(r['mean_ms']/1000) if r['mean_ms'] else 0,'status':'MEASURED_PUBLIC_DATASET'})

# User-supplied opaque forensic artifacts: acquisition/segment/Merkle and digest re-verification only.
for path in sorted(p for p in USER.iterdir() if p.is_file()):
    total=path.stat().st_size; use=min(total,MAX_BYTES); truncated=use<total
    acq=[]; verify=[]; segs=0
    for _ in range(max(3,min(REPS,7))):
        t=time.perf_counter_ns(); leaves=[]; seen=0
        with path.open('rb') as f:
            while seen<use:
                b=f.read(min(4096,use-seen))
                if not b: break
                leaves.append(hashlib.sha256(b).digest()); seen+=len(b)
        root=merkle(leaves); acq.append(time.perf_counter_ns()-t); segs=len(leaves)
        t=time.perf_counter_ns(); leaves2=[]; seen=0
        with path.open('rb') as f:
            while seen<use:
                b=f.read(min(4096,use-seen))
                if not b: break
                leaves2.append(hashlib.sha256(b).digest()); seen+=len(b)
        ok=merkle(leaves2)==root; verify.append(time.perf_counter_ns()-t)
        if not ok: raise RuntimeError(f'opaque artifact verification failed for {path}')
    a=ms_stats(acq); v=ms_stats(verify)
    rows.append({'experiment':'C3','dataset':path.name,'source':'user-supplied','bytes':use,'records':'','segments':segs,'pii_fields_detected':'','segment_mode':'4096-byte block','reps':len(acq),
                 'acquisition_mean_ms':a['mean_ms'],'acquisition_p95_ms':a['p95_ms'],'masking_mean_ms':'','masking_p95_ms':'','verify_mean_ms':v['mean_ms'],'verify_p95_ms':v['p95_ms'],
                 'throughput_MiB_s':(use/(1024**2))/(a['mean_ms']/1000) if a['mean_ms'] else 0,'status':'MEASURED_USER_ARTIFACT_PREFIX' if truncated else 'MEASURED_USER_ARTIFACT'})

if rows:
    p=OUT/'dataset_bench.csv'
    with p.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print(f'wrote {p} ({len(rows)} rows)')
else:
    print('No datasets available; nothing to benchmark.')
