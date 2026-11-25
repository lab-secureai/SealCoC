#!/usr/bin/env python3
from pathlib import Path
import json, math, statistics
import pandas as pd
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[1]
R=ROOT/'results'; P=R/'plots'; P.mkdir(parents=True,exist_ok=True)
rows=[]

def add(group,metric,value,unit,status='MEASURED'):
    rows.append({'group':group,'metric':metric,'value':value,'unit':unit,'status':status})

def summarize_raw(path,col='latency_ms'):
    df=pd.read_csv(path); x=df[col].astype(float).tolist(); x.sort()
    return statistics.mean(x),statistics.median(x),x[max(0,math.ceil(.95*len(x))-1)]

# SNARK
sp=R/'snark'/'snark_bench.csv'
if sp.exists():
    df=pd.read_csv(sp)
    for _,r in df.iterrows():
        n=int(r.size_B)
        add('SNARK',f'{n}B constraints',int(r.constraints),'constraints')
        add('SNARK',f'{n}B prove mean',round(r.prove_mean_ms,3),'ms')
        add('SNARK',f'{n}B verify mean',round(r.verify_mean_ms,3),'ms')
        add('SNARK',f'{n}B prove peak RSS',int(r.prove_peak_rss_kib_max)/1024,'MiB')
        add('SNARK',f'{n}B proof JSON',round(r.proof_json_bytes_mean,1),'bytes')
    fig,ax=plt.subplots(figsize=(7,4.5)); ax.plot(df.size_B,df.prove_mean_ms,marker='o',label='Prove'); ax.plot(df.size_B,df.verify_mean_ms,marker='o',label='Verify'); ax.set_xscale('log',base=2); ax.set_yscale('log'); ax.set_xlabel('Segment size (bytes)'); ax.set_ylabel('Latency (ms)'); ax.set_title('Groth16 scaling'); ax.legend(); ax.grid(True,alpha=.25); fig.tight_layout(); fig.savefig(P/'snark_scaling.png',dpi=180); plt.close(fig)

# Fabric raw
for fn,label in [('fabric_verify_query.csv','Peer query: embedded Groth16 verify'),('fabric_submit_tx.csv','Ordered SubmitRedaction tx')]:
    p=R/'fabric'/fn
    if p.exists():
        mean,med,p95=summarize_raw(p); add('Fabric',label+' mean',round(mean,3),'ms');add('Fabric',label+' median',round(med,3),'ms');add('Fabric',label+' p95',round(p95,3),'ms')
pt=R/'fabric'/'fabric_throughput.csv'
if pt.exists():
    x=pd.read_csv(pt).iloc[0]; add('Fabric','Concurrent throughput',float(x.throughput_tx_s),'tx/s');add('Fabric','Concurrent failed tx',int(x.failed),'tx')
pa=R/'fabric'/'fabric_adversarial.csv'
if pa.exists():
    d=pd.read_csv(pa); add('Fabric','Adversarial tests passed',int(d['pass'].astype(str).str.lower().eq('true').sum()),f'/ {len(d)}')

# EVM
pe=R/'evm'/'evm_gas.csv'
if pe.exists():
    d=pd.read_csv(pe); kv=dict(zip(d.metric,d.value));
    for k in ['deployment_gas','verify_estimate_gas','verify_tx_gas']:
        if k in kv:add('EVM',k,int(kv[k]),'gas')

# local crypto highlights
lc=R/'local_crypto'
for fn in ['e2_merkle.csv','e3_batch.csv','e5_adversarial.csv','e7_case_study.csv','e8_ablation.csv']:
    if (lc/fn).exists(): pass
p=lc/'e2_merkle.csv'
if p.exists():
    d=pd.read_csv(p); z=d[d.leaf_count==d.leaf_count.max()].iloc[0];add('Local','Merkle max leaves',int(z.leaf_count),'leaves');add('Local','Merkle max build mean',round(z.mean_ms,3),'ms')
p=lc/'e5_adversarial.csv'
if p.exists():
    d=pd.read_csv(p); ok=d['pass'].astype(str).str.lower().eq('true');add('Security','Local adversarial tests passed',int(ok.sum()),f'/ {len(d)}')

summary=pd.DataFrame(rows); summary.to_csv(R/'paper_summary.csv',index=False)
md=['# SEAL-CoC paper-ready experiment summary','', '> Generated automatically. Only rows marked MEASURED are suitable for empirical claims; modeled/proxy rows retain their status in source CSVs.','']
if len(summary):
    md.append(summary.to_markdown(index=False))
md += ['', '## Source result directories', '', '- `local_crypto/`: primitive, Merkle, quorum proxy, adversarial, ablation and case-study measurements.', '- `snark/`: Circom/Groth16 constraints, prove/verify latency, proof size and peak RSS.', '- `fabric/`: Fabric embedded-verifier latency, ordered transactions, 3-of-4 certificate approvals, adversarial tests and throughput.', '- `evm/`: local EVM Groth16 verifier deployment/verification gas.', '- `environment.txt`: complete software/hardware/version record.']
(R/'paper_summary.md').write_text('\n'.join(md),encoding='utf-8')
print(summary.to_string(index=False))
