#!/usr/bin/env python3
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import statistics, math, json, os, textwrap

ROOT=Path(__file__).resolve().parents[1]
R=ROOT/'results'; O=R/'paper_ready'; T=O/'tables'; F=O/'figures'
for p in (O,T,F): p.mkdir(parents=True,exist_ok=True)

# ---------- helpers ----------
def read(rel):
    p=R/rel
    if not p.exists(): return None
    try: return pd.read_csv(p)
    except Exception as e:
        print('WARN cannot read',p,e); return None

def num(s): return pd.to_numeric(s,errors='coerce')
def p95(s):
    x=sorted(num(s).dropna().tolist())
    return x[min(len(x)-1,max(0,math.ceil(.95*len(x))-1))] if x else float('nan')
def stat_series(s):
    x=num(s).dropna().tolist()
    if not x: return {'n':0,'mean':float('nan'),'median':float('nan'),'p95':float('nan'),'sd':float('nan'),'ci95':float('nan')}
    sd=statistics.stdev(x) if len(x)>1 else 0.0
    return {'n':len(x),'mean':statistics.mean(x),'median':statistics.median(x),'p95':p95(pd.Series(x)),'sd':sd,'ci95':1.96*sd/math.sqrt(len(x)) if len(x)>1 else 0.0}
def fmt(x,d=2):
    try:
        if pd.isna(x): return '—'
        return f'{float(x):,.{d}f}'
    except: return str(x)
def save_table(df,name,caption='',label=''):
    df.to_csv(T/f'{name}.csv',index=False)
    (T/f'{name}.md').write_text((f'**{caption}**\n\n' if caption else '')+df.to_markdown(index=False),encoding='utf-8')
    tex=df.to_latex(index=False,escape=True,float_format=lambda x:f'{x:.3f}',caption=caption or None,label=label or None,position='t')
    (T/f'{name}.tex').write_text(tex,encoding='utf-8')

def savefig(fig,name):
    fig.tight_layout(); fig.savefig(F/f'{name}.png',dpi=300,bbox_inches='tight'); fig.savefig(F/f'{name}.pdf',bbox_inches='tight'); plt.close(fig)

def aggregate_raw(df,group,col='latency_ms'):
    rows=[]
    for k,g in df.groupby(group):
        s=stat_series(g[col]); row={group:k,'n':s['n'],'mean_ms':s['mean'],'median_ms':s['median'],'p95_ms':s['p95'],'sd_ms':s['sd'],'ci95_ms':s['ci95']}; rows.append(row)
    return pd.DataFrame(rows)

claims=[]; captions=[]; completeness=[]
def check(name,rel,required=True):
    p=R/rel; ok=p.exists() and p.stat().st_size>0
    completeness.append({'item':name,'path':rel,'required':required,'present':ok,'status':'OK' if ok else ('MISSING_REQUIRED' if required else 'MISSING_OPTIONAL')})
    return ok

# ---------- expected inputs ----------
for item,rel,req in [
 ('SNARK scaling','snark/snark_bench.csv',True),('SNARK mask ratio','snark/snark_mask_ratio.csv',True),
 ('Fabric verify by size','fabric_paper/f1_verify_by_size.csv',True),('Fabric ordered submit by size','fabric_paper/f2_submit_by_size.csv',True),
 ('Fabric throughput scaling','fabric_paper/f3_throughput_scaling.csv',True),('Fabric workflow','fabric_paper/f4_workflow.csv',True),('Fabric WAN netem','fabric_paper/f8_wan_netem.csv',False),
 ('Fabric measured storage','fabric_paper/f5_storage_growth.csv',False),('Fabric adversarial','fabric_paper/f6_adversarial.csv',True),
 ('True end-to-end','fabric_paper/f7_true_end_to_end.csv',True),('EVM gas','evm/evm_gas.csv',True),
 ('Local primitives','local_crypto/e1_microbench.csv',True),('Merkle scaling','local_crypto/e2_merkle.csv',True),
 ('Batch scaling','local_crypto/e3_batch.csv',True),('Local adversarial','local_crypto/e5_adversarial.csv',True),
 ('Forensic case study','local_crypto/e7_case_study.csv',True),('Ablation','local_crypto/e8_ablation.csv',True),
 ('Public/user datasets','datasets/dataset_bench.csv',True),('Published-code baselines','baselines/literature_baselines.csv',False),
 ('Environment','environment.txt',True)]: check(item,rel,req)
pd.DataFrame(completeness).to_csv(O/'COMPLETENESS.csv',index=False)

# ---------- T1 / F1: SNARK scaling ----------
sn=read('snark/snark_bench.csv')
if sn is not None:
    sn=sn.copy(); sn['prove_peak_MiB']=num(sn.prove_peak_rss_kib_max)/1024
    cols=['size_B','constraints','reps','witness_mean_ms','witness_p95_ms','prove_mean_ms','prove_p95_ms','verify_mean_ms','verify_p95_ms','prove_peak_MiB','proof_json_bytes_mean']
    st=sn[cols].copy(); st.columns=['Segment (B)','Constraints','n','Witness mean (ms)','Witness p95 (ms)','Prove mean (ms)','Prove p95 (ms)','Verify mean (ms)','Verify p95 (ms)','Prover peak RSS (MiB)','Proof JSON (B)']
    save_table(st,'T1_snark_scalability','Groth16 scalability as a function of segment size.','tab:snark_scaling')
    fig,ax=plt.subplots(figsize=(6.8,4.5)); ax.plot(sn.size_B,num(sn.constraints),marker='o'); ax.set_xscale('log',base=2); ax.set_yscale('log'); ax.set_xlabel('Segment size (bytes)'); ax.set_ylabel('R1CS constraints'); ax.grid(True,alpha=.25); savefig(fig,'F1_constraints_scaling'); captions.append('F1. R1CS constraint growth with segment size.')
    fig,ax=plt.subplots(figsize=(6.8,4.5)); ax.plot(sn.size_B,num(sn.prove_mean_ms),marker='o',label='Prove'); ax.plot(sn.size_B,num(sn.verify_mean_ms),marker='o',label='Verify'); ax.set_xscale('log',base=2); ax.set_yscale('log'); ax.set_xlabel('Segment size (bytes)'); ax.set_ylabel('Latency (ms, log scale)'); ax.legend(); ax.grid(True,alpha=.25); savefig(fig,'F2_snark_latency'); captions.append('F2. Groth16 proving and verification latency across segment sizes.')
    fig,ax=plt.subplots(figsize=(6.8,4.5)); ax.plot(sn.size_B,sn.prove_peak_MiB,marker='o'); ax.set_xscale('log',base=2); ax.set_xlabel('Segment size (bytes)'); ax.set_ylabel('Peak prover RSS (MiB)'); ax.grid(True,alpha=.25); savefig(fig,'F3_prover_memory'); captions.append('F3. Peak memory consumed by the Groth16 prover.')
    z=sn.loc[num(sn.size_B).idxmax()]
    claims.append(f"The largest {int(z.size_B):,}-byte circuit contained {int(z.constraints):,} constraints; proof generation averaged {fmt(z.prove_mean_ms)} ms and verification averaged {fmt(z.verify_mean_ms)} ms, with a peak prover RSS of {fmt(z.prove_peak_MiB)} MiB.")
    if len(sn)>1:
        a=sn.iloc[0]; b=sn.iloc[-1]; claims.append(f"From {int(a.size_B)} B to {int(b.size_B)} B, constraint count increased by {float(b.constraints)/float(a.constraints):.2f}×, while the serialized Groth16 proof remained approximately constant ({fmt(a.proof_json_bytes_mean,0)}–{fmt(b.proof_json_bytes_mean,0)} B).")

# ---------- T2/F4 mask-ratio sensitivity ----------
mr=read('snark/snark_mask_ratio.csv')
if mr is not None:
    t=mr[['size_B','mask_ratio','mask_count_public','reps','prove_mean_ms','prove_p95_ms','verify_mean_ms','verify_p95_ms']].copy(); t['mask_ratio']=num(t.mask_ratio)*100
    t.columns=['Segment (B)','Masked (%)','Public mask count','n','Prove mean (ms)','Prove p95 (ms)','Verify mean (ms)','Verify p95 (ms)']
    save_table(t,'T2_mask_ratio_sensitivity','Sensitivity of proof cost to the fraction of masked bytes.','tab:mask_ratio')
    fig,ax=plt.subplots(figsize=(6.8,4.5))
    for size,g in mr.groupby('size_B'): ax.plot(num(g.mask_ratio)*100,num(g.prove_mean_ms),marker='o',label=f'{int(size)} B')
    ax.set_xlabel('Masked bytes (%)'); ax.set_ylabel('Prove latency (ms)'); ax.legend(); ax.grid(True,alpha=.25); savefig(fig,'F4_mask_ratio_sensitivity'); captions.append('F4. Proof-generation latency versus the fraction of masked bytes for fixed-size circuits.')
    for size,g in mr.groupby('size_B'):
        xs=num(g.prove_mean_ms); cv=float(xs.std(ddof=1)/xs.mean()*100) if len(xs)>1 else 0
        claims.append(f"For the {int(size)}-byte circuit, varying the mask ratio from {100*float(num(g.mask_ratio).min()):.0f}% to {100*float(num(g.mask_ratio).max()):.0f}% changed proving time with a cross-condition coefficient of variation of {cv:.2f}%, consistent with fixed circuit complexity.")

# ---------- T3 / F5 Fabric size scaling ----------
fv=read('fabric_paper/f1_verify_by_size.csv'); fs=read('fabric_paper/f2_submit_by_size.csv')
if fv is not None and fs is not None:
    av=aggregate_raw(fv,'size_B'); ass=aggregate_raw(fs,'size_B')
    m=av.merge(ass,on='size_B',suffixes=('_verify','_submit'))
    t=m[['size_B','n_verify','mean_ms_verify','p95_ms_verify','n_submit','mean_ms_submit','p95_ms_submit']].copy(); t.columns=['Segment (B)','Verify n','Fabric verify mean (ms)','Fabric verify p95 (ms)','Submit n','Ordered submit mean (ms)','Ordered submit p95 (ms)']
    save_table(t,'T3_fabric_by_size','Fabric embedded-verifier and ordered-transaction latency by circuit size.','tab:fabric_size')
    fig,ax=plt.subplots(figsize=(6.8,4.5)); ax.plot(m.size_B,m.mean_ms_verify,marker='o',label='Peer query / verify'); ax.plot(m.size_B,m.mean_ms_submit,marker='o',label='Ordered SubmitRedaction'); ax.set_xscale('log',base=2); ax.set_yscale('log'); ax.set_xlabel('Circuit segment size (bytes)'); ax.set_ylabel('Latency (ms, log scale)'); ax.legend(); ax.grid(True,alpha=.25); savefig(fig,'F5_fabric_latency_by_size'); captions.append('F5. Fabric latency with embedded Groth16 verification across circuit sizes.')
    claims.append(f"Across all circuit sizes, Fabric-side Groth16 verification averaged {fmt(av.mean_ms.mean())} ms; ordered SubmitRedaction transactions averaged {fmt(ass.mean_ms.mean())} ms.")

# ---------- T4/F6 throughput ----------
th=read('fabric_paper/f3_throughput_scaling.csv')
if th is not None:
    t=th[['concurrency','transactions','successful','failed','elapsed_ms','throughput_tx_s']].copy(); t.columns=['Concurrency','Transactions','Successful','Failed','Elapsed (ms)','Throughput (tx/s)']; save_table(t,'T4_fabric_throughput','Fabric SubmitRedaction throughput under increasing client concurrency.','tab:fabric_throughput')
    fig,ax=plt.subplots(figsize=(6.8,4.5)); ax.plot(num(th.concurrency),num(th.throughput_tx_s),marker='o'); ax.set_xlabel('Concurrent clients'); ax.set_ylabel('Successful transactions/s'); ax.grid(True,alpha=.25); savefig(fig,'F6_fabric_throughput'); captions.append('F6. Successful SubmitRedaction throughput versus client concurrency.')
    best=th.loc[num(th.throughput_tx_s).idxmax()]; claims.append(f"Peak measured Fabric throughput was {fmt(best.throughput_tx_s)} successful redaction submissions/s at concurrency {int(best.concurrency)}, with {int(best.failed)} failed transactions in that run.")

# ---------- T5/F7 workflow ----------
wf=read('fabric_paper/f4_workflow.csv')
if wf is not None:
    phasecols=['submit_ms','approve_I_ms','approve_P_ms','approve_C_ms','commit_ms','end_to_end_ms']; rr=[]
    for c in phasecols:
        s=stat_series(wf[c]); rr.append({'Phase':c.replace('_ms',''),'n':s['n'],'Mean (ms)':s['mean'],'Median (ms)':s['median'],'p95 (ms)':s['p95'],'95% CI ± (ms)':s['ci95']})
    tt=pd.DataFrame(rr); save_table(tt,'T5_quorum_workflow','Latency breakdown of the certificate-bound 3-of-4 redaction workflow.','tab:workflow')
    fig,ax=plt.subplots(figsize=(7.2,4.5)); p=tt[tt.Phase!='end_to_end']; ax.bar(p.Phase,p['Mean (ms)']); ax.set_ylabel('Mean latency (ms)'); ax.tick_params(axis='x',rotation=25); ax.grid(True,axis='y',alpha=.25); savefig(fig,'F7_workflow_breakdown'); captions.append('F7. Mean latency of submission, three certificate-bound approvals, and final commit.')
    e=stat_series(wf.end_to_end_ms); claims.append(f"A complete pre-proved 3-of-4 Fabric workflow (submission, three approvals, and commit) averaged {fmt(e['mean'])} ms (p95 {fmt(e['p95'])} ms).")

# ---------- T6/F8 WAN netem ----------
wan=read('fabric_paper/f8_wan_netem.csv')
if wan is not None:
    wan=wan[num(wan.end_to_end_ms).notna()].copy()
if wan is not None and len(wan):
    rr=[]
    for rtt,g in wan.groupby('target_rtt_ms'):
        ss=stat_series(g.end_to_end_ms); rr.append({'Target RTT label (ms)':int(rtt),'Injected one-way delay (ms)':float(num(g.injected_one_way_ms).iloc[0]),'n':ss['n'],'Workflow mean (ms)':ss['mean'],'Workflow p95 (ms)':ss['p95'],'95% CI ± (ms)':ss['ci95']})
    wt=pd.DataFrame(rr).sort_values('Target RTT label (ms)'); save_table(wt,'T6_wan_netem','Complete 3-of-4 Fabric workflow under container-network delay emulation.','tab:wan_netem')
    fig,ax=plt.subplots(figsize=(6.8,4.5)); ax.plot(wt['Target RTT label (ms)'],wt['Workflow mean (ms)'],marker='o'); ax.set_xlabel('Target RTT label (ms)'); ax.set_ylabel('Mean workflow latency (ms)'); ax.grid(True,alpha=.25); savefig(fig,'F8_wan_netem'); captions.append('F8. Sensitivity of the complete pre-proved 3-of-4 workflow to emulated peer/orderer network delay.')
    b=wt.iloc[0]; z=wt.iloc[-1]; claims.append(f"Under container-network emulation, complete pre-proved workflow latency rose from {fmt(b['Workflow mean (ms)'])} ms at the zero-delay profile to {fmt(z['Workflow mean (ms)'])} ms at the {int(z['Target RTT label (ms)'])}-ms target-RTT profile.")

# ---------- T7/F9 true e2e ----------
e2e=read('fabric_paper/f7_true_end_to_end.csv')
if e2e is not None:
    rr=[]
    for size,g in e2e.groupby('size_B'):
        row={'Segment (B)':int(size),'n':len(g)}
        for c in ['witness_ms','prove_ms','submit_ms','approvals_ms','commit_ms','end_to_end_ms']:
            s=stat_series(g[c]); row[c.replace('_ms','')+' mean (ms)']=s['mean']; row[c.replace('_ms','')+' p95 (ms)']=s['p95']
        rr.append(row)
    tt=pd.DataFrame(rr); save_table(tt,'T7_true_end_to_end','True end-to-end workflow including fresh witness/proof generation and on-ledger 3-of-4 commit.','tab:true_e2e')
    fig,ax=plt.subplots(figsize=(7,4.8)); x=range(len(tt)); bottom=[0.0]*len(tt)
    for key in ['witness','prove','submit','approvals','commit']:
        vals=num(tt[f'{key} mean (ms)']).tolist(); ax.bar(x,vals,bottom=bottom,label=key); bottom=[a+b for a,b in zip(bottom,vals)]
    ax.set_xticks(list(x),[str(v) for v in tt['Segment (B)']]); ax.set_xlabel('Segment size (bytes)'); ax.set_ylabel('Mean true end-to-end latency (ms)'); ax.legend(); ax.grid(True,axis='y',alpha=.25); savefig(fig,'F9_true_e2e_breakdown'); captions.append('F9. True end-to-end latency including local proof generation and the full 3-of-4 ledger workflow.')
    for size,g in e2e.groupby('size_B'):
        s=stat_series(g.end_to_end_ms); claims.append(f"For {int(size):,}-byte segments, true end-to-end redact-and-commit latency averaged {fmt(s['mean'])} ms (p95 {fmt(s['p95'])} ms), including fresh Groth16 proof generation.")

# ---------- T8/F10 storage ----------
st=read('fabric_paper/f5_storage_growth.csv')
if st is not None:
    save_table(st,'T8_ledger_storage','Measured Fabric peer storage growth while persisting redaction requests.','tab:storage')
    good=st[num(st.redactions)>0].copy(); good['delta_bytes']=num(good.delta_bytes); good=good.dropna(subset=['delta_bytes'])
    if len(good):
        fig,ax=plt.subplots(figsize=(6.8,4.5)); ax.plot(num(good.redactions),num(good.delta_bytes)/(1024**2),marker='o'); ax.set_xlabel('Stored redaction requests'); ax.set_ylabel('Incremental peer storage (MiB, two peers)'); ax.grid(True,alpha=.25); savefig(fig,'F10_storage_growth'); captions.append('F10. Measured Fabric storage growth after persisting redaction requests.')
        last=good.iloc[-1]; claims.append(f"At {int(last.redactions)} stored requests, the two Fabric peers grew by {fmt(float(last.delta_bytes)/(1024**2),3)} MiB relative to the pre-redaction baseline ({fmt(last.bytes_per_redaction,0)} bytes/request averaged over that run).")

# ---------- T9 security ----------
la=read('local_crypto/e5_adversarial.csv'); fa=read('fabric_paper/f6_adversarial.csv'); sec=[]
if la is not None:
    for _,r in la.iterrows(): sec.append({'Layer':'Local/crypto','Attack':r.attack,'Expected':r.expected,'Observed':r.observed,'Pass':str(r['pass']).lower()=='true','Detail':r.detail})
if fa is not None:
    for _,r in fa.iterrows(): sec.append({'Layer':'Fabric','Attack':r.test,'Expected':r.expected,'Observed':r.observed,'Pass':str(r['pass']).lower()=='true','Detail':r.detail})
if sec:
    tt=pd.DataFrame(sec); save_table(tt,'T9_adversarial_security','Adversarial evaluation against the SEAL-CoC threat model.','tab:security')
    summ=tt.groupby('Layer').Pass.agg(['sum','count']).reset_index(); summ['rate_pct']=summ['sum']/summ['count']*100
    fig,ax=plt.subplots(figsize=(6.5,4.2)); ax.bar(summ.Layer,summ.rate_pct); ax.set_ylim(0,105); ax.set_ylabel('Tests meeting expected outcome (%)'); ax.grid(True,axis='y',alpha=.25); savefig(fig,'F11_adversarial_results'); captions.append('F11. Fraction of adversarial tests producing the expected accept/reject outcome.')
    claims.append(f"The adversarial suite produced the expected outcome in {int(tt.Pass.sum())}/{len(tt)} tests across local cryptographic logic and Fabric enforcement.")

# ---------- T10 local scaling and figures ----------
me=read('local_crypto/e2_merkle.csv')
if me is not None:
    t=me[['leaf_count','height','reps','mean_ms','p95_ms','throughput_leaves_s']].copy(); t.columns=['Leaves','Tree height','n','Mean (ms)','p95 (ms)','Leaves/s']; save_table(t,'T10_merkle_scaling','Merkle-tree construction scalability.','tab:merkle')
    fig,ax=plt.subplots(figsize=(6.8,4.5)); ax.plot(num(me.leaf_count),num(me.mean_ms),marker='o'); ax.set_xscale('log',base=2); ax.set_yscale('log'); ax.set_xlabel('Leaves'); ax.set_ylabel('Build latency (ms)'); ax.grid(True,alpha=.25); savefig(fig,'F12_merkle_scaling'); captions.append('F12. Merkle-tree build latency from 2^10 to 2^20 leaves.')
    z=me.loc[num(me.leaf_count).idxmax()]; claims.append(f"A Merkle tree with {int(z.leaf_count):,} leaves was constructed in {fmt(z.mean_ms)} ms on average ({fmt(z.throughput_leaves_s,0)} leaves/s).")
ba=read('local_crypto/e3_batch.csv')
if ba is not None:
    t=ba[['segments','segment_B','mode','reps','mean_ms','p95_ms','throughput_segments_s']]; save_table(t,'T11_batch_preprocessing','Batch commitment and mask-verification preprocessing.','tab:batch')
    fig,ax=plt.subplots(figsize=(6.8,4.5));
    for mode,g in ba.groupby('mode'): ax.plot(num(g.segments),num(g.throughput_segments_s),marker='o',label=mode)
    ax.set_xscale('log'); ax.set_xlabel('1-KiB segments'); ax.set_ylabel('Segments/s'); ax.legend(); ax.grid(True,alpha=.25); savefig(fig,'F13_batch_throughput'); captions.append('F13. Batch preprocessing throughput in sequential and five-thread modes.')

cs=read('local_crypto/e7_case_study.csv')
if cs is not None:
    save_table(cs,'T12_synthetic_case_study','Synthetic forensic case study with privacy-sensitive IP fields.','tab:case_study')
    fig,ax=plt.subplots(figsize=(6.8,4.5)); ax.plot(num(cs.records),num(cs.end_to_end_mean_ms),marker='o',label='End-to-end preprocessing'); ax.plot(num(cs.records),num(cs.independent_verify_mean_ms),marker='o',label='Independent verify'); ax.set_xscale('log'); ax.set_yscale('log'); ax.set_xlabel('Records / PII fields'); ax.set_ylabel('Latency (ms)'); ax.legend(); ax.grid(True,alpha=.25); savefig(fig,'F14_case_study'); captions.append('F14. Scaling of the synthetic forensic redaction and independent-verification workload.')

# ---------- T13/F15 public/user datasets ----------
ds=read('datasets/dataset_bench.csv')
if ds is not None:
    save_table(ds,'T13_dataset_results','Measured workload results on public logs and user-supplied forensic artifacts.','tab:datasets')
    pub=ds[ds.status.astype(str).str.contains('PUBLIC')].copy()
    if len(pub):
        fig,ax=plt.subplots(figsize=(7,4.5)); ax.bar(pub.dataset,num(pub.throughput_MiB_s)); ax.set_ylabel('Masking throughput (MiB/s)'); ax.tick_params(axis='x',rotation=20); ax.grid(True,axis='y',alpha=.25); savefig(fig,'F15_public_dataset_throughput'); captions.append('F15. Masking throughput on public Loghub evidence datasets.')
        for _,r in pub.iterrows(): claims.append(f"On {r.dataset}, the line-preserving redaction workload detected {int(r.pii_fields_detected)} IP/e-mail fields and processed masking at {fmt(r.throughput_MiB_s)} MiB/s.")

# ---------- T14 baselines ----------
bl=read('baselines/literature_baselines.csv')
if bl is not None:
    save_table(bl,'T14_published_code_baselines','Reproduction of public redactable-blockchain baseline code on 1-MiB blocks (different workload from SEAL-CoC segments).','tab:baselines')
    good=bl[num(bl.mean_ms).notna()].copy()
    if len(good):
        labels=(good.baseline.str.replace(' implementation','',regex=False)+'\n'+good.operation).tolist(); fig,ax=plt.subplots(figsize=(9,4.8)); ax.bar(range(len(good)),num(good.mean_ms)); ax.set_xticks(range(len(good)),labels,rotation=30,ha='right'); ax.set_ylabel('Mean latency (ms), 1-MiB blocks'); ax.grid(True,axis='y',alpha=.25); savefig(fig,'F16_published_code_baselines'); captions.append('F16. Reproduced 1-MiB performance of public SHA-256 and redactable-chameleon-hash baseline implementations; these workloads are not directly normalized to SEAL-CoC segment sizes.')

# ---------- T15/F17 EVM ----------
ev=read('evm/evm_gas.csv')
if ev is not None:
    save_table(ev,'T15_evm_gas','Gas cost of the generated Groth16 verifier on the local EVM.','tab:evm_gas')
    good=ev[num(ev.value).notna()].copy(); fig,ax=plt.subplots(figsize=(6.8,4.5)); ax.bar(good.metric,num(good.value)); ax.set_ylabel('Gas'); ax.tick_params(axis='x',rotation=25); ax.grid(True,axis='y',alpha=.25); savefig(fig,'F17_evm_gas'); captions.append('F17. Deployment and verification gas for the generated Groth16 verifier.')

# ---------- ablation / composed cost ----------
ab=read('local_crypto/e8_ablation.csv')
if ab is not None:
    # Do not overwrite pending full-SEAL rows with a fake number. Add a separate derived-cost table when components exist.
    save_table(ab,'T16_local_ablation','Controlled local ablation. CH and quorum rows are explicitly labelled as proxies in the raw data.','tab:ablation')
    derived=[]
    if sn is not None and wf is not None:
        for N in sorted(set(num(sn.size_B).dropna().astype(int))):
            sr=sn[num(sn.size_B)==N].iloc[0]; w=stat_series(wf.end_to_end_ms)
            derived.append({'Segment (B)':N,'Groth16 prove mean (ms)':float(sr.prove_mean_ms),'Pre-proved Fabric workflow mean (ms)':w['mean'],'Derived combined mean (ms)':float(sr.prove_mean_ms)+w['mean'],'status':'DERIVED_FROM_MEASURED_COMPONENTS_NOT_SINGLE_STOPWATCH'})
    if derived: save_table(pd.DataFrame(derived),'T17_derived_cost_attribution','Cost attribution obtained by adding independently measured proof-generation and pre-proved Fabric workflow components; not a single-stopwatch end-to-end measurement.','tab:derived_cost')

# ---------- paper narrative ----------
comp=pd.DataFrame(completeness); missing=comp[(comp.required==True)&(comp.present==False)]
header='# SEAL-CoC — Paper-ready evaluation package\n\n'
status=('**Completeness:** all required result families are present.\n' if len(missing)==0 else '**Completeness warning:** missing required result families: '+', '.join(missing.item.tolist())+'.\n')
(O/'README_PAPER_READY.md').write_text(header+status+'\nThe `tables/` directory contains CSV/Markdown/LaTeX versions; `figures/` contains 300-DPI PNG and vector PDF figures. Values are generated from raw experiment CSVs and are not manually embedded.\n',encoding='utf-8')
(O/'FIGURE_CAPTIONS.md').write_text('# Proposed figure captions\n\n'+'\n\n'.join(captions),encoding='utf-8')
(O/'KEY_EMPIRICAL_CLAIMS.md').write_text('# Empirical claims generated from measured results\n\n'+'\n'.join(f'- {c}' for c in claims),encoding='utf-8')

# Draft Results section, intentionally cautious on causality and generalization.
paras=['# 6. Implementation and Evaluation — auto-generated draft','',
'## 6.1 Experimental methodology',
'We evaluate SEAL-CoC along five dimensions: cryptographic scalability, ledger/workflow overhead, adversarial robustness, forensic-workload scalability, and cost attribution. Unless explicitly marked as a proxy, modeled value, derived value, or third-party baseline, all quantitative claims below are generated from measured raw CSV files. Timing results retain the repetition counts used by the corresponding experiment and report p95 where raw repetitions are available. The full hardware and software configuration is recorded in `environment.txt`.','',
'## 6.2 Main results']
paras += [c for c in claims]
paras += ['', '## 6.3 Security evaluation', 'The adversarial experiments are implementation checks rather than substitutes for the formal security reductions. Their purpose is to demonstrate that the deployed enforcement path rejects malformed proofs, insufficient or duplicated approvals, cross-evidence replays, and stale-version attempts in the conditions covered by the test suite.','',
'## 6.4 Threats to validity',
'Local WSL measurements describe the evaluated machine and should not be generalized to production consortium deployments without additional multi-host measurements. The Ed25519 local quorum experiment is a multi-signature proxy rather than an implementation of the final threshold-signature construction. The classic chameleon-hash microbenchmark is also a proxy and is intentionally not key-exposure free. Public-code baseline measurements use the upstream implementation\'s native 1-MiB workload and therefore should be reported as a separate reproduction rather than as a normalized head-to-head latency comparison. The deterministic setup entropy used for reproducible local benchmarking must not be used as a production trusted setup.']
(O/'RESULTS_SECTION_DRAFT.md').write_text('\n\n'.join(paras),encoding='utf-8')

# RQ answer sheet
rq=['# Research-question answer sheet','',
'**Research question 1 — Cryptographic scalability.** Use Tables T1–T2 and Figures F1–F4. Report the largest circuit, proving time, memory, proof-size stability, and mask-ratio sensitivity.','',
'**Research question 2 — Ledger/workflow overhead.** Use Tables T3–T8 and Figures F5–F10. Distinguish verifier-only queries, ordered submissions, pre-proved workflow latency, and true end-to-end latency including proof generation.','',
'**Research question 3 — Security.** Use Table T9 and Figure F11 together with the formal games/theorems. Do not claim that testing proves cryptographic security.','',
'**Research question 4 — Forensic scalability.** Use Tables T10–T13 and Figures F12–F15. Public Loghub results are real-dataset measurements; opaque user artifacts measure acquisition/integrity processing only.','',
'**Research question 5 — Cost/baselines.** Use Tables T14–T17 and Figures F16–F17. Keep proxy/derived/third-party-code labels visible.']
(O/'RQ_ANSWERS.md').write_text('\n'.join(rq),encoding='utf-8')

# Consolidated artifacts for convenient paper writing.
all_tables=['# All generated tables','']
for mdp in sorted(T.glob('T*.md')):
    all_tables += [f'## {mdp.stem}', '', mdp.read_text(encoding='utf-8'), '']
(O/'ALL_TABLES.md').write_text('\n'.join(all_tables),encoding='utf-8')
layout='''# Suggested paper layout

## Main text

- **Table 1 / T1:** Groth16 scalability.
- **Table 2 / T3:** Fabric verification and ordered submission by circuit size.
- **Table 3 / T4:** Throughput scaling.
- **Table 4 / T7:** True end-to-end latency including proof generation.
- **Table 5 / T9:** Adversarial/security outcomes.
- **Table 6 / T13:** Real/public forensic workload results.
- **Figure 1 / F2:** SNARK prove/verify scaling.
- **Figure 2 / F6:** Fabric throughput vs concurrency.
- **Figure 3 / F8:** WAN/netem sensitivity.
- **Figure 4 / F9:** True end-to-end phase breakdown.
- **Figure 5 / F11:** Adversarial outcome rate.
- **Figure 6 / F15:** Public-dataset throughput.

## Appendix / supplementary material

Use mask-ratio sensitivity, prover memory, workflow phase details, storage growth, Merkle/batch microbenchmarks, EVM gas, ablation, and third-party public-code reproduction as supplementary material unless the target venue gives enough space.

Do not combine proxy, modeled, derived, and measured results in the same bar chart without explicit labels.
'''
(O/'PAPER_LAYOUT.md').write_text(layout,encoding='utf-8')
(O/'NUMBERS_FOR_ABSTRACT.md').write_text('# Candidate numbers for abstract/conclusion\n\n'+'\n'.join(f'- {c}' for c in claims[:8]),encoding='utf-8')
raw=['# Raw-data index','']
for rp in sorted(R.rglob('*.csv')):
    if O in rp.parents: continue
    raw.append(f'- `{rp.relative_to(R)}`')
(O/'RAW_DATA_INDEX.md').write_text('\n'.join(raw),encoding='utf-8')

# Self-contained HTML index for quick review/printing in a browser.
import html as _html
html_parts=['<!doctype html><html><head><meta charset="utf-8"><title>SEAL-CoC Paper Results</title>',
'<style>body{font-family:Arial,sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;line-height:1.45}table{border-collapse:collapse;width:100%;font-size:13px;margin:12px 0 28px}th,td{border:1px solid #bbb;padding:6px;text-align:left}img{max-width:100%;height:auto;margin:10px 0 28px}code{background:#f3f3f3;padding:2px 4px}.warn{background:#fff4d6;padding:10px}</style></head><body>',
'<h1>SEAL-CoC — Paper-ready evaluation results</h1>', f'<p>{_html.escape(status)}</p>', '<h2>Key empirical claims</h2><ul>']
for c in claims: html_parts.append('<li>'+_html.escape(c)+'</li>')
html_parts.append('</ul><h2>Figures</h2>')
for fp in sorted(F.glob('F*.png')):
    html_parts.append(f'<h3>{_html.escape(fp.stem)}</h3><img src="figures/{fp.name}">')
html_parts.append('<h2>Tables</h2>')
for cp in sorted(T.glob('T*.csv')):
    try:
        dfh=pd.read_csv(cp); html_parts.append(f'<h3>{_html.escape(cp.stem)}</h3>'+dfh.to_html(index=False,border=0))
    except Exception: pass
html_parts.append('</body></html>')
(O/'REPORT.html').write_text('\n'.join(html_parts),encoding='utf-8')

# Master table list and manifest
files=[]
for p in sorted(O.rglob('*')):
    if p.is_file(): files.append({'file':str(p.relative_to(O)),'bytes':p.stat().st_size})
pd.DataFrame(files).to_csv(O/'MANIFEST.csv',index=False)
print(f'Paper-ready package: {O}')
print(f'Tables: {len(list(T.glob("*.tex")))}; figures: {len(list(F.glob("*.png")))}; claims: {len(claims)}')
if len(missing): print('MISSING REQUIRED:', ', '.join(missing.item.tolist()))
