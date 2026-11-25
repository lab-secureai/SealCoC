import argparse, subprocess, pathlib, time, csv, re, statistics, os, json

def run(cmd,cwd=None,check=True):
    p = subprocess.run(cmd,cwd=cwd,text=True,capture_output=True)
    if p.returncode != 0 and check:
        import sys, shlex
        print("\n[COMMAND FAILED]", " ".join(shlex.quote(str(x)) for x in cmd), file=sys.stderr)
        if p.stdout:
            print("--- stdout ---", file=sys.stderr)
            print(p.stdout, file=sys.stderr)
        if p.stderr:
            print("--- stderr ---", file=sys.stderr)
            print(p.stderr, file=sys.stderr)
        raise subprocess.CalledProcessError(p.returncode, cmd, output=p.stdout, stderr=p.stderr)
    return p

def timed(cmd,cwd=None):
    t=time.perf_counter(); p=run(cmd,cwd); return (time.perf_counter()-t)*1000,p


def timed_rss(cmd,cwd=None,rss_file=None):
    rss_file = pathlib.Path(rss_file or '/tmp/seal_time_rss.txt')
    wrapped=['/usr/bin/time','-v','-o',str(rss_file)]+cmd
    t=time.perf_counter(); p=run(wrapped,cwd); ms=(time.perf_counter()-t)*1000
    rss=None
    if rss_file.exists():
        m=re.search(r'Maximum resident set size \(kbytes\):\s*(\d+)',rss_file.read_text(errors='ignore'))
        if m: rss=int(m.group(1))
    return ms,p,rss

def parse_constraints(txt):
    pats=[r'Constraints:\s*(\d+)',r'# of Constraints:\s*(\d+)',r'constraints:\s*(\d+)']
    for pat in pats:
        m=re.search(pat,txt,re.I)
        if m:return int(m.group(1))
    return None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--circom',default='circom'); ap.add_argument('--snarkjs',default='snarkjs')
    ap.add_argument('--ptau',required=True); ap.add_argument('--reps',type=int,default=10)
    ap.add_argument('--sizes',default='64,128,256,512,1024,2048,4096')
    ap.add_argument('--root',default=str(pathlib.Path(__file__).resolve().parents[1]))
    a=ap.parse_args(); root=pathlib.Path(a.root); out=root/'snark_results'; out.mkdir(exist_ok=True)
    rows=[]
    for N in map(int,a.sizes.split(',')):
        b=out/f'n{N}'; b.mkdir(exist_ok=True)
        src=root/'circuits'/f'mask_{N}.circom'
        # Compile. -l points to npm-installed circomlib package root.
        compile_ms,p=timed([a.circom,str(src),'--r1cs','--wasm','--sym','--O1','-l',str(root/'node_modules'),'-o',str(b)])
        r1cs=b/f'mask_{N}.r1cs'; jsdir=b/f'mask_{N}_js'; wasm=jsdir/f'mask_{N}.wasm'
        info=run([a.snarkjs,'r1cs','info',str(r1cs)]); constraints=parse_constraints(info.stdout+info.stderr)
        setup_ms,_=timed([a.snarkjs,'groth16','setup',str(r1cs),a.ptau,str(b/'circuit_0000.zkey')])
        run([a.snarkjs,'zkey','contribute',str(b/'circuit_0000.zkey'),str(b/'circuit_final.zkey'),'--name=SEAL-CoC benchmark contribution',f'-e=SEAL-CoC-{N}-20261017','-v'])
        run([a.snarkjs,'zkey','export','verificationkey',str(b/'circuit_final.zkey'),str(b/'verification_key.json')])
        run(['python3',str(root/'snark_harness'/'make_input.py'),str(N),str(b/'input.json')])
        witness_times=[]; prove_times=[]; verify_times=[]; proof_sizes=[]; witness_rss=[]; prove_rss=[]; verify_rss=[]
        for rep in range(a.reps):
            w=b/f'witness_{rep}.wtns'; proof=b/f'proof_{rep}.json'; pub=b/f'public_{rep}.json'
            ms,_,rss=timed_rss(['node',str(jsdir/'generate_witness.js'),str(wasm),str(b/'input.json'),str(w)],rss_file=b/f'time_w_{rep}.txt'); witness_times.append(ms); witness_rss.append(rss or 0)
            ms,_,rss=timed_rss([a.snarkjs,'groth16','prove',str(b/'circuit_final.zkey'),str(w),str(proof),str(pub)],rss_file=b/f'time_p_{rep}.txt'); prove_times.append(ms); prove_rss.append(rss or 0)
            ms,vp,rss=timed_rss([a.snarkjs,'groth16','verify',str(b/'verification_key.json'),str(pub),str(proof)],rss_file=b/f'time_v_{rep}.txt'); verify_times.append(ms); verify_rss.append(rss or 0)
            if 'OK!' not in (vp.stdout+vp.stderr) and 'OK' not in (vp.stdout+vp.stderr): raise RuntimeError('verify failed')
            proof_sizes.append(proof.stat().st_size)
        rows.append({
          'size_B':N,'constraints':constraints,'compile_ms':compile_ms,'setup_ms':setup_ms,'reps':a.reps,
          'witness_mean_ms':statistics.mean(witness_times),'witness_p95_ms':sorted(witness_times)[max(0,int(.95*len(witness_times))-1)],
          'prove_mean_ms':statistics.mean(prove_times),'prove_p95_ms':sorted(prove_times)[max(0,int(.95*len(prove_times))-1)],
          'verify_mean_ms':statistics.mean(verify_times),'verify_p95_ms':sorted(verify_times)[max(0,int(.95*len(verify_times))-1)],
          'proof_json_bytes_mean':statistics.mean(proof_sizes),
          'witness_peak_rss_kib_max':max(witness_rss),'prove_peak_rss_kib_max':max(prove_rss),'verify_peak_rss_kib_max':max(verify_rss),
          'r1cs_bytes':r1cs.stat().st_size,'wasm_bytes':wasm.stat().st_size,'status':'MEASURED_SNARK'
        })
        print(json.dumps(rows[-1],indent=2))
    with open(out/'snark_bench.csv','w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
if __name__=='__main__': main()
