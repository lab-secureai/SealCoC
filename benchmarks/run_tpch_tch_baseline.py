#!/usr/bin/env python3
import argparse,csv,importlib.util,math,os,statistics,time,secrets
from pathlib import Path

def stats(xs):
    xs=list(xs); ys=sorted(xs); n=len(xs); sd=statistics.stdev(xs) if n>1 else 0.0
    p95=ys[min(n-1,max(0,math.ceil(.95*n)-1))]
    tc={1:12.706,2:4.303,3:3.182,4:2.776,5:2.571,6:2.447,7:2.365,8:2.306,9:2.262,10:2.228,11:2.201,12:2.179,13:2.160,14:2.145,15:2.131,16:2.120,17:2.110,18:2.101,19:2.093,20:2.086,21:2.080,22:2.074,23:2.069,24:2.064,25:2.060,26:2.056,27:2.052,28:2.048,29:2.045,30:2.042}.get(max(1,n-1),1.96)
    return dict(n=n,mean_ms=statistics.mean(xs),median_ms=statistics.median(xs),p95_ms=p95,sd_ms=sd,ci95_ms=tc*sd/math.sqrt(n) if n>1 else 0.0)

def timed(fn,reps,warm=2):
    for _ in range(warm): fn()
    out=[]
    for _ in range(reps):
        t=time.perf_counter_ns(); fn(); out.append((time.perf_counter_ns()-t)/1e6)
    return stats(out)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--tch',required=True); ap.add_argument('--out',required=True); ap.add_argument('--reps',type=int,default=20); ap.add_argument('--commit',required=True); a=ap.parse_args()
    spec=importlib.util.spec_from_file_location('tpch_tch',a.tch); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    param={'rsa_modulus_length_in_bits':2048,'number_parties_needed':3,'number_parties_corrupted':0,'number_parties_total':4,'delta':math.factorial(4)}
    # Fixed upstream safe-prime constants make setup deterministic enough for a reproducible implementation baseline.
    setup_cache={}
    def setup_once(): return m.TCH_setup(dict(param))
    sk_unshared,pk=m.TCH_setup(dict(param)); sk_shared=m.TCH_KGen(dict(param),sk_unshared,pk)
    msg=secrets.token_bytes(1024); msg2=secrets.token_bytes(1024)
    h,r=m.VV_Hash(pk,msg)
    shares,proofs=m.VV_ParAdapt(dict(param),pk,sk_shared,msg,msg2,r)
    m.VV_ParVer(dict(param),pk,sk_shared,proofs,msg,msg2,r,shares)
    rp=m.VV_Combine(dict(param),pk,shares,msg,msg2,r)
    assert m.VV_Verify(pk,msg2,rp,h)==1
    rows=[]
    def add(op,fn,reps=None,warm=2):
        s=timed(fn,reps or a.reps,warm); rows.append({'baseline':'TPCH repository TCH core (3-of-4)','operation':op,'message_size_B':1024,'threshold':'3-of-4','n':s['n'],'mean_ms':s['mean_ms'],'median_ms':s['median_ms'],'p95_ms':s['p95_ms'],'sd_ms':s['sd_ms'],'ci95_ms':s['ci95_ms'],'source_commit':a.commit,'status':'MEASURED_THIRD_PARTY_MODERN_THRESHOLD_CODE'})
    add('TCH.Setup',lambda:m.TCH_setup(dict(param)),max(5,a.reps//2),1)
    add('TCH.KGen',lambda:m.TCH_KGen(dict(param),sk_unshared,pk))
    add('TCH.Hash',lambda:m.VV_Hash(pk,msg))
    add('TCH.Verify',lambda:m.VV_Verify(pk,msg,r,h))
    add('TCH.ParAdapt (4 shares + proofs)',lambda:m.VV_ParAdapt(dict(param),pk,sk_shared,msg,msg2,r))
    add('TCH.ParVer (4 shares)',lambda:m.VV_ParVer(dict(param),pk,sk_shared,proofs,msg,msg2,r,shares))
    add('TCH.Combine (threshold=3)',lambda:m.VV_Combine(dict(param),pk,shares,msg,msg2,r))
    out=Path(a.out); out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
    print(f'wrote {out} ({len(rows)} operations); correctness collision check passed')
if __name__=='__main__': main()
