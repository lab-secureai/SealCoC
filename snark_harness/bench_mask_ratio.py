#!/usr/bin/env python3
import argparse, pathlib, subprocess, time, csv, json, hashlib, random, statistics, math
P=21888242871839275222246405745257275088548364400416034343698204186575808495617

def run(cmd):
    p=subprocess.run(cmd,text=True,capture_output=True)
    if p.returncode:
        print('COMMAND FAILED:', ' '.join(map(str,cmd)))
        print(p.stdout); print(p.stderr)
        raise subprocess.CalledProcessError(p.returncode,cmd,p.stdout,p.stderr)
    return p

def stats(xs):
    ys=sorted(xs); n=len(ys); sd=statistics.stdev(ys) if n>1 else 0.0
    return {'mean_ms':statistics.mean(ys),'median_ms':statistics.median(ys),'p95_ms':ys[min(n-1,max(0,math.ceil(.95*n)-1))],'stdev_ms':sd,'ci95_ms':1.96*sd/math.sqrt(n) if n>1 else 0.0}

def fld(tag,N): return str(int.from_bytes(hashlib.sha256((tag+str(N)).encode()).digest(),'big')%P)
def make_input(N,ratio,out):
    rng=random.Random(20261017+N+int(ratio*1000))
    orig=[rng.randrange(32,127) for _ in range(N)]; mask=[0]*N
    k=max(1,min(N,int(round(N*ratio))))
    for i in rng.sample(range(N),k): mask[i]=1
    red=[42 if mask[i] else orig[i] for i in range(N)]
    obj={'orig':orig,'red':red,'mask':mask,'rhoOrig':fld('rhoO-ratio',N),'rhoRed':fld('rhoR-ratio',N),'context':fld('case-ratio|',N),'maxMask':str(N//2)}
    pathlib.Path(out).write_text(json.dumps(obj))
    return k

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default=str(pathlib.Path(__file__).resolve().parents[1])); ap.add_argument('--snarkjs',default='snarkjs'); ap.add_argument('--reps',type=int,default=10); ap.add_argument('--sizes',default='1024,4096'); ap.add_argument('--ratios',default='0.05,0.10,0.25,0.50'); a=ap.parse_args()
    root=pathlib.Path(a.root); out=root/'results'/'snark'; out.mkdir(parents=True,exist_ok=True); rows=[]
    for N in map(int,a.sizes.split(',')):
        d=root/'snark_results'/f'n{N}'; js=d/f'mask_{N}_js'; wasm=js/f'mask_{N}.wasm'; zkey=d/'circuit_final.zkey'; vk=d/'verification_key.json'
        for f in [wasm,zkey,vk]:
            if not f.exists(): raise SystemExit(f'missing prerequisite {f}; run base Groth16 benchmark first')
        for ratio in map(float,a.ratios.split(',')):
            inp=d/f'input_ratio_{int(ratio*100):02d}.json'; k=make_input(N,ratio,inp)
            wt=[]; pt=[]; vt=[]; psz=[]; observed=None
            for rep in range(a.reps):
                w=d/f'ratio_{int(ratio*100):02d}_{rep}.wtns'; proof=d/f'ratio_{int(ratio*100):02d}_{rep}_proof.json'; pub=d/f'ratio_{int(ratio*100):02d}_{rep}_public.json'
                t=time.perf_counter(); run(['node',str(js/'generate_witness.js'),str(wasm),str(inp),str(w)]); wt.append((time.perf_counter()-t)*1000)
                t=time.perf_counter(); run([a.snarkjs,'groth16','prove',str(zkey),str(w),str(proof),str(pub)]); pt.append((time.perf_counter()-t)*1000)
                t=time.perf_counter(); p=run([a.snarkjs,'groth16','verify',str(vk),str(pub),str(proof)]); vt.append((time.perf_counter()-t)*1000)
                if 'OK' not in p.stdout+p.stderr: raise RuntimeError('Groth16 verify did not report OK')
                vals=json.loads(pub.read_text()); observed=int(vals[2]); psz.append(proof.stat().st_size)
            sw,sp,sv=stats(wt),stats(pt),stats(vt)
            rows.append({'experiment':'S2','size_B':N,'mask_ratio':ratio,'mask_count_expected':k,'mask_count_public':observed,'reps':a.reps,
                         'witness_mean_ms':sw['mean_ms'],'witness_p95_ms':sw['p95_ms'],'prove_mean_ms':sp['mean_ms'],'prove_p95_ms':sp['p95_ms'],'verify_mean_ms':sv['mean_ms'],'verify_p95_ms':sv['p95_ms'],
                         'proof_json_bytes_mean':statistics.mean(psz),'status':'MEASURED_SNARK_MASK_RATIO'})
            print(rows[-1])
    with (out/'snark_mask_ratio.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
if __name__=='__main__': main()
