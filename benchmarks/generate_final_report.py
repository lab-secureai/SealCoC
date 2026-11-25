#!/usr/bin/env python3
from pathlib import Path
import pandas as pd, numpy as np, math, statistics, shutil, json, os
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1]; R=ROOT/'results'; O=R/'final_report'; T=O/'tables'; F=O/'figures'
for p in (O,T,F): p.mkdir(parents=True,exist_ok=True)
def read(rel):
    p=R/rel
    if not p.exists(): return None
    try:return pd.read_csv(p)
    except Exception as e: print('WARN',p,e); return None
def num(x):return pd.to_numeric(x,errors='coerce')
def tcrit95(n):
    # two-sided Student-t 97.5th percentile; normal approximation after df>30
    vals={1:12.706,2:4.303,3:3.182,4:2.776,5:2.571,6:2.447,7:2.365,8:2.306,9:2.262,10:2.228,11:2.201,12:2.179,13:2.160,14:2.145,15:2.131,16:2.120,17:2.110,18:2.101,19:2.093,20:2.086,21:2.080,22:2.074,23:2.069,24:2.064,25:2.060,26:2.056,27:2.052,28:2.048,29:2.045,30:2.042}
    return vals.get(max(1,n-1),1.96)
def sstat(s):
    x=num(s).dropna().tolist(); n=len(x)
    if not n:return dict(n=0,mean=np.nan,median=np.nan,p95=np.nan,sd=np.nan,ci95=np.nan)
    x.sort(); sd=statistics.stdev(x) if n>1 else 0.; p95=x[min(n-1,max(0,math.ceil(.95*n)-1))]
    return dict(n=n,mean=statistics.mean(x),median=statistics.median(x),p95=p95,sd=sd,ci95=tcrit95(n)*sd/math.sqrt(n) if n>1 else 0.)
def fmt(x,d=2):
    try:return '—' if pd.isna(x) else f'{float(x):,.{d}f}'
    except:return str(x)
def save(df,name,caption,label):
    df.to_csv(T/f'{name}.csv',index=False); (T/f'{name}.md').write_text(f'**{caption}**\n\n'+df.to_markdown(index=False),encoding='utf-8'); (T/f'{name}.tex').write_text(df.to_latex(index=False,escape=True,float_format=lambda x:f'{x:.3f}',caption=caption,label=label,position='t'),encoding='utf-8')
def figsave(fig,name):
    fig.tight_layout(); fig.savefig(F/f'{name}.png',dpi=300,bbox_inches='tight'); fig.savefig(F/f'{name}.pdf',bbox_inches='tight'); plt.close(fig)

gates=[]
def gate(name,ok,detail,critical=True):gates.append({'gate':name,'critical':critical,'pass':bool(ok),'detail':detail})

# Fabric size scaling
v1=read('final_validation/fabric/verify_by_size.csv'); v2=read('final_validation/fabric/submit_by_size.csv')
if v1 is not None and v2 is not None:
    rows=[]
    for size in sorted(set(num(v1.size_B).dropna().astype(int))):
        a=sstat(v1[num(v1.size_B)==size].latency_ms); b=sstat(v2[num(v2.size_B)==size].latency_ms)
        rows.append({'Segment (B)':size,'Verify n':a['n'],'Verify mean (ms)':a['mean'],'Verify median (ms)':a['median'],'Verify p95 (ms)':a['p95'],'Verify 95% CI ± (ms)':a['ci95'],'Submit n':b['n'],'Submit mean (ms)':b['mean'],'Submit p95 (ms)':b['p95'],'Submit 95% CI ± (ms)':b['ci95']})
    df=pd.DataFrame(rows); save(df,'fabric_verification','Final Fabric embedded-verifier and ordered submission latency, measured with CLOCK_MONOTONIC_RAW after warm-up.','tab:seal_fabric_size')
    gate('No non-positive Fabric verify latency',(num(v1.latency_ms)>0).all(),f'min={num(v1.latency_ms).min():.3f} ms')
    gate('Fabric verify repetitions >=30',all(df['Verify n']>=30),str(df['Verify n'].tolist()))
    fig,ax=plt.subplots(figsize=(7,4.5)); ax.errorbar(df['Segment (B)'],df['Verify mean (ms)'],yerr=df['Verify 95% CI ± (ms)'],marker='o',capsize=3,label='Peer query + Groth16 verify'); ax.errorbar(df['Segment (B)'],df['Submit mean (ms)'],yerr=df['Submit 95% CI ± (ms)'],marker='o',capsize=3,label='Ordered SubmitRedaction'); ax.set_xscale('log',base=2); ax.set_yscale('log'); ax.set_xlabel('Circuit segment size (B)'); ax.set_ylabel('Latency (ms, log scale)'); ax.grid(True,alpha=.25); ax.legend(); figsave(fig,'fabric_verification')
else: gate('Final Fabric-by-size results present',False,'missing verifier or submission series',True)

# Throughput across independent runs
th=read('final_validation/fabric/throughput_runs.csv')
if th is not None:
    rows=[]
    for c,g in th.groupby('concurrency'):
        s=sstat(g.throughput_tx_s); rows.append({'Concurrency':int(c),'Independent runs':s['n'],'Transactions/run':int(num(g.transactions).median()),'Mean throughput (tx/s)':s['mean'],'Median (tx/s)':s['median'],'p95 (tx/s)':s['p95'],'95% CI ± (tx/s)':s['ci95'],'Total failed':int(num(g.failed).sum())})
    dfth=pd.DataFrame(rows).sort_values('Concurrency'); save(dfth,'fabric_throughput','Fabric throughput over independent runs at each client concurrency.','tab:seal_throughput')
    gate('Throughput >=5 independent runs/concurrency',all(dfth['Independent runs']>=5),str(dfth['Independent runs'].tolist()))
    fig,ax=plt.subplots(figsize=(7,4.5)); ax.errorbar(dfth.Concurrency,dfth['Mean throughput (tx/s)'],yerr=dfth['95% CI ± (tx/s)'],marker='o',capsize=4); ax.set_xlabel('Concurrent clients'); ax.set_ylabel('Throughput (successful tx/s)'); ax.grid(True,alpha=.25); figsave(fig,'fabric_throughput')
else: gate('Final throughput results present',False,'missing throughput series',True)

# workflow
wf=read('final_validation/fabric/authorization_workflow.csv')
if wf is not None:
    rows=[]
    for c in ['submit_ms','approve_I_ms','approve_P_ms','approve_C_ms','commit_ms','end_to_end_ms']:
        s=sstat(wf[c]); rows.append({'Phase':c[:-3],'n':s['n'],'Mean (ms)':s['mean'],'Median (ms)':s['median'],'p95 (ms)':s['p95'],'SD (ms)':s['sd'],'95% CI ± (ms)':s['ci95']})
    dfwf=pd.DataFrame(rows); save(dfwf,'authorization_workflow','Warmed 3-of-4 certificate-bound workflow phase latency.','tab:seal_workflow')
    gate('Workflow repetitions >=20',len(wf)>=20,f'n={len(wf)}')
    fig,ax=plt.subplots(figsize=(7.5,4.5)); p=dfwf[dfwf.Phase!='end_to_end']; ax.bar(p.Phase,p['Mean (ms)'],yerr=p['95% CI ± (ms)'],capsize=3); ax.set_ylabel('Mean latency (ms)'); ax.tick_params(axis='x',rotation=25); ax.grid(True,axis='y',alpha=.25); figsave(fig,'authorization_workflow')
else: gate('Final workflow results present',False,'missing workflow series',True)

# WAN
wan=read('final_validation/fabric/wan_netem.csv')
if wan is not None:
    rows=[]
    for rtt,g in wan[num(wan.end_to_end_ms).notna()].groupby('target_rtt_ms'):
        s=sstat(g.end_to_end_ms); actual=num(g.measured_rtt_ms).dropna(); rows.append({'Configured RTT label (ms)':int(rtt),'Injected one-way (ms)':float(num(g.injected_one_way_ms).median()),'Measured peer RTT mean (ms)':float(actual.mean()) if len(actual) else np.nan,'n':s['n'],'Workflow mean (ms)':s['mean'],'Workflow median (ms)':s['median'],'Workflow p95 (ms)':s['p95'],'95% CI ± (ms)':s['ci95']})
    dfwan=pd.DataFrame(rows).sort_values('Configured RTT label (ms)'); save(dfwan,'network_delay','Complete 3-of-4 workflow under verified Linux netem delay; measured peer RTT is reported separately from configured delay.','tab:seal_wan')
    gate('WAN repetitions >=10/profile',len(dfwan)>0 and all(dfwan.n>=10),str(dfwan.n.tolist() if len(dfwan) else []))
    gate('WAN actual peer RTT measured',dfwan['Measured peer RTT mean (ms)'].notna().all() if len(dfwan) else False,str(dfwan['Measured peer RTT mean (ms)'].tolist() if len(dfwan) else []),False)
    fig,ax=plt.subplots(figsize=(7,4.5)); x=dfwan['Measured peer RTT mean (ms)'].fillna(dfwan['Configured RTT label (ms)']); ax.errorbar(x,dfwan['Workflow mean (ms)'],yerr=dfwan['95% CI ± (ms)'],marker='o',capsize=4); ax.set_xlabel('Measured peer RTT (ms)'); ax.set_ylabel('3-of-4 workflow latency (ms)'); ax.grid(True,alpha=.25); figsave(fig,'network_delay')
else: gate('Final WAN results present',False,'missing WAN series',False)

#  true E2E
e2e=read('final_validation/fabric/true_end_to_end.csv')
if e2e is not None:
    rows=[]
    for size,g in e2e.groupby('size_B'):
        row={'Segment (B)':int(size)}
        for c,label in [('witness_ms','Witness'),('prove_ms','Prove'),('submit_ms','Submit'),('approvals_ms','3 approvals'),('commit_ms','Commit'),('end_to_end_ms','End-to-end')]:
            s=sstat(g[c]); row[f'{label} mean (ms)']=s['mean']; row[f'{label} p95 (ms)']=s['p95']; row[f'{label} 95% CI ± (ms)']=s['ci95']; row['n']=s['n']
        rows.append(row)
    dfe=pd.DataFrame(rows).sort_values('Segment (B)'); save(dfe,'end_to_end_latency','True end-to-end latency from fresh witness/proof generation through certificate-bound 3-of-4 ledger commit.','tab:seal_e2e')
    gate('True E2E repetitions >=10/size',all(dfe.n>=10),str(dfe.n.tolist()))
    fig,ax=plt.subplots(figsize=(7.2,4.6)); x=np.arange(len(dfe)); bottom=np.zeros(len(dfe));
    for label in ['Witness','Prove','Submit','3 approvals','Commit']:
        vals=num(dfe[f'{label} mean (ms)']).to_numpy(); ax.bar(x,vals,bottom=bottom,label=label); bottom+=vals
    ax.set_xticks(x,[f'{int(v)} B' for v in dfe['Segment (B)']]); ax.set_ylabel('Mean end-to-end latency (ms)'); ax.legend(fontsize=8); ax.grid(True,axis='y',alpha=.2); figsave(fig,'end_to_end_latency')
else: gate('Final true E2E results present',False,'missing ',True)

# Modern threshold TCH baseline
mb=read('final_validation/baselines/tpch_tch_core.csv')
if mb is not None:
    save(mb,'threshold_baseline','Pinned TPCH repository TCH-core reproduction configured as 3-of-4. This is a separate implementation baseline, not the integrated SEAL-CoC authorization layer.','tab:seal_tchbaseline')
    gate('Modern 3-of-4 threshold baseline reproduced',len(mb)>=6,f'{len(mb)} operations')
    fig,ax=plt.subplots(figsize=(9,4.6)); ax.bar(mb.operation,num(mb.mean_ms),yerr=num(mb.ci95_ms),capsize=3); ax.set_yscale('log'); ax.set_ylabel('Mean latency (ms, log scale)'); ax.tick_params(axis='x',rotation=32); ax.grid(True,axis='y',alpha=.25); figsave(fig,'threshold_baseline')
else: gate('Modern 3-of-4 threshold baseline reproduced',False,'missing TPCH TCH-core benchmark',True)

# Final datasets
ds=read('final_validation/datasets/final_dataset_bench.csv')
if ds is not None:
    save(ds,'forensic_workloads','Additional network and binary-artifact validation workloads. Synthetic binary images are explicitly labeled and are not presented as real forensic cases.','tab:seal_datasets')
    gate('Real network dataset measured',(ds.status=='MEASURED_REAL_NETWORK_DATASET').any(),', '.join(ds.dataset.astype(str)))
    gate('Binary artifact modality measured',ds.status.str.contains('BINARY_IMAGE|USER_FORENSIC_ARTIFACT',regex=True).any(),', '.join(ds.status.astype(str)),False)
    p=ds[num(ds.throughput_MiB_s).notna()];
    if len(p):
        fig,ax=plt.subplots(figsize=(8,4.5)); ax.bar(p.dataset,num(p.throughput_MiB_s)); ax.set_ylabel('Processing throughput (MiB/s)'); ax.tick_params(axis='x',rotation=25); ax.grid(True,axis='y',alpha=.25); figsave(fig,'forensic_workloads')
else: gate('Final network/binary datasets present',False,'missing final dataset results',True)

# Re-use foundational results for readiness gates.
sn=read('snark/snark_bench.csv'); adv=read('fabric_paper/f6_adversarial.csv'); lad=read('local_crypto/e5_adversarial.csv')
if sn is not None:
    z=sn[num(sn.size_B)==4096]; gate('4-KiB Groth16 result present',len(z)>0,f'constraints={int(z.iloc[0].constraints) if len(z) else "n/a"}, reps={int(z.iloc[0].reps) if len(z) else "n/a"}')
else: gate('Groth16 results present',False,'missing snark_bench',True)
if adv is not None: gate('Fabric adversarial tests all pass',adv['pass'].astype(str).str.lower().eq('true').all(),f'{adv[adv["pass"].astype(str).str.lower()=="true"].shape[0]}/{len(adv)} passed')
else: gate('Fabric adversarial tests present',False,'missing',True)
if lad is not None: gate('Local adversarial tests all pass',lad['pass'].astype(str).str.lower().eq('true').all(),f'{lad[lad["pass"].astype(str).str.lower()=="true"].shape[0]}/{len(lad)} passed')

G=pd.DataFrame(gates); G.to_csv(O/'QUALITY_GATES.csv',index=False); (O/'QUALITY_GATES.md').write_text(G.to_markdown(index=False),encoding='utf-8')
critical=G[G.critical==True]; ready=bool(len(critical) and critical['pass'].all())
# Claims
claims=[]
if sn is not None and len(sn):
    z=sn.loc[num(sn.size_B).idxmax()]; claims.append(f"The 4-KiB Groth16 circuit contains {int(z.constraints):,} constraints; proof generation averages {fmt(z.prove_mean_ms)} ms with {fmt(num(pd.Series([z.prove_peak_rss_kib_max])).iloc[0]/1024)} MiB peak RSS.")
if e2e is not None:
    for size,g in e2e.groupby('size_B'):
        s=sstat(g.end_to_end_ms); claims.append(f"For {int(size):,}-byte segments, true end-to-end redact-and-commit latency is {fmt(s['mean']/1000,3)} s on average (n={s['n']}, p95={fmt(s['p95']/1000,3)} s, 95% CI ±{fmt(s['ci95']/1000,3)} s).")
if th is not None:
    agg=[]
    for c,g in th.groupby('concurrency'): agg.append((int(c),sstat(g.throughput_tx_s)))
    c,s=max(agg,key=lambda x:x[1]['mean']); claims.append(f"Peak mean Fabric submission throughput is {fmt(s['mean'])} tx/s at concurrency {c} over {s['n']} independent runs (95% CI ±{fmt(s['ci95'])} tx/s).")
if adv is not None: claims.append(f"The on-ledger adversarial suite rejected/handled all expected cases in {len(adv)} measured tests." if adv['pass'].astype(str).str.lower().eq('true').all() else 'The on-ledger adversarial suite contains at least one failed expectation; inspect QUALITY_GATES.csv.')
(O/'FINAL_MANUSCRIPT_NUMBERS.md').write_text('# Final manuscript numbers\n\n'+'\n'.join('- '+x for x in claims)+'\n',encoding='utf-8')
limitations=[
'The certificate-bound 3-of-4 Fabric workflow is the integrated authorization prototype; the threshold chameleon-hash implementation is benchmarked separately from the pinned TPCH repository and is not integrated into the Fabric transaction path.',
'The synthetic EXT4 image is a binary-modality stress workload, not a real forensic case. If a CFReDS or other real disk image is placed in datasets/input,  benchmarks up to the configured prefix and labels it as user-supplied forensic evidence.',
'Netem results are single-host namespace emulation and should not be described as a geographically distributed multi-host deployment.',
'The reproducible SNARK setup uses deterministic benchmark entropy and must not be represented as a production trusted-setup ceremony.'
]
status='FINAL VALIDATION-VALIDATION GATES PASSED' if ready else 'NOT YET SUBMISSION-READY: one or more critical gates failed'
(O/'SUBMISSION_READINESS.md').write_text(f'# {status}\n\n## Quality gates\n\n'+G.to_markdown(index=False)+'\n\n## Required wording limitations\n\n'+'\n'.join(f'- {x}' for x in limitations)+'\n',encoding='utf-8')
# Short results draft
parts=['# Final Validation Results','',f'**Status:** {status}.','', '## Robust Fabric timing','']
if v1 is not None: parts.append('The final validation replaces wall-clock timing with Linux `CLOCK_MONOTONIC_RAW`, performs warm-up executions, and repeats verifier measurements at least 30 times per circuit size. This removes the WSL clock-correction artifact that produced a negative latency in the preliminary run.')
if th is not None: parts += ['', '## Throughput', 'Throughput is estimated from five independent runs per concurrency setting; the final table reports run-level uncertainty rather than a single burst measurement.']
if wf is not None: parts += ['', '## Quorum workflow', 'The certificate-bound 3-of-4 workflow is measured after explicit warm-up and with at least 20 repetitions, allowing mean, median, p95, standard deviation, and 95% confidence intervals to be reported.']
if e2e is not None: parts += ['', '## True end-to-end latency', 'End-to-end measurements include fresh witness generation, Groth16 proof generation, ordered submission, three distinct certificate approvals, and final ledger commit.']
parts += ['', '## Interpretation limits', *['- '+x for x in limitations]]
(O/'FINAL_RESULTS_DRAFT.md').write_text('\n'.join(parts)+'\n',encoding='utf-8')
# Index
idx=['# final package','','Use these final-validation tables/figures in preference to preliminary T3–T7 from .','','## Tables']+[f'- `{p.name}`' for p in sorted(T.glob('*.tex'))]+['','## Figures']+[f'- `{p.name}`' for p in sorted(F.glob('*.pdf'))]
(O/'README.md').write_text('\n'.join(idx)+'\n',encoding='utf-8')
# Consolidated print-ready material.
all_tables=['# All final-validation tables','']
for md in sorted(T.glob('*.md')):
    all_tables += [f'## {md.stem}','',md.read_text(encoding='utf-8'),'']
(O/'ALL_FINAL_TABLES.md').write_text('\n'.join(all_tables),encoding='utf-8')
capmap={
'fabric_verification':'Final Fabric verifier/query and ordered submission latency by circuit size; error bars show 95% confidence intervals.',
'fabric_throughput':'Successful ordered redaction-submission throughput across five independent runs per concurrency level; error bars show 95% confidence intervals.',
'authorization_workflow':'Latency breakdown of the warmed certificate-bound 3-of-4 workflow; error bars show 95% confidence intervals.',
'network_delay':'Complete workflow latency versus measured peer-to-peer RTT under single-host Linux network-namespace delay emulation.',
'end_to_end_latency':'True end-to-end latency composition from fresh witness/proof generation through final ledger commit.',
'threshold_baseline':'Pinned public TPCH-repository TCH-core reproduction configured 3-of-4; log-scale operation latency.',
'forensic_workloads':'Processing throughput for additional network and binary-artifact validation workloads.'}
(O/'FIGURE_CAPTIONS.md').write_text('# Final figure captions\n\n'+'\n'.join(f'- **{k}:** {v}' for k,v in capmap.items())+'\n',encoding='utf-8')
# Abstract-safe numbers are emitted only from final measurements.
abs_lines=['# Numbers safe to consider for the abstract','']
if sn is not None and len(sn):
    z=sn.loc[num(sn.size_B).idxmax()]; abs_lines.append(f'- 4-KiB circuit: **{int(z.constraints):,} constraints**, proof generation **{fmt(z.prove_mean_ms)} ms**; peak prover RSS **{fmt(num(pd.Series([z.prove_peak_rss_kib_max])).iloc[0]/1024)} MiB**.')
if e2e is not None:
    for size,g in e2e.groupby('size_B'):
        st=sstat(g.end_to_end_ms); abs_lines.append(f'- True E2E {int(size):,} B: **{fmt(st["mean"]/1000,3)} s mean**, **{fmt(st["p95"]/1000,3)} s p95**, n={st["n"]}.')
if th is not None:
    tmp=[]
    for c,g in th.groupby('concurrency'): tmp.append((int(c),sstat(g.throughput_tx_s)))
    c,st=max(tmp,key=lambda x:x[1]['mean']); abs_lines.append(f'- Peak Fabric submission throughput: **{fmt(st["mean"])} tx/s** at concurrency {c}, over {st["n"]} independent runs.')
(O/'NUMBERS_FOR_ABSTRACT.md').write_text('\n'.join(abs_lines)+'\n',encoding='utf-8')
# Final RQ mapping.
rq=['# Final RQ answers','',
'## Research question 1 — Cryptographic scalability','Use the existing  T1/T2 plus the final E2E table Q5. The 4-KiB proof is the largest evaluated circuit and should anchor the scalability discussion.','',
'## Research question 2 — Ledger/workflow overhead','Use the ledger, workflow and end-to-end tables and figures. These measurements supersede preliminary ones because they use monotonic timing, warm-up, higher repetition counts, and independent throughput runs.','',
'## Research question 3 — Adversarial robustness','Use the existing on-ledger adversarial table from  together with the quality gates. Keep the distinction between transformation soundness and governance legitimacy explicit.','',
'## Research question 4 — Forensic/workload scalability','Use existing Loghub/Merkle/batch results plus Q7. CIC-IDS2017 is a real network-flow workload; the generated EXT4 image is explicitly synthetic unless a real image is supplied.','',
'## Research question 5 — Baselines and cost attribution','Use the corrected classic baseline output plus Q6. Q6 is a modern 3-of-4 threshold TCH-core reproduction, but it is not integrated into the Fabric path.']
(O/'RQ_FINAL_ANSWERS.md').write_text('\n'.join(rq)+'\n',encoding='utf-8')
# A self-contained browser report for printing/review.
html=['<!doctype html><html><head><meta charset="utf-8"><title>SEAL-CoC Final Validation</title><style>body{font-family:Arial,sans-serif;max-width:1200px;margin:30px auto;padding:0 20px;line-height:1.45}table{border-collapse:collapse;width:100%;margin:12px 0 28px}th,td{border:1px solid #bbb;padding:6px;font-size:12px}img{max-width:100%;height:auto;margin:8px 0 30px}.pass{font-weight:bold}pre{white-space:pre-wrap}</style></head><body>',f'<h1>SEAL-CoC Final Validation</h1><p><b>{status}</b></p>','<h2>Quality gates</h2>',G.to_html(index=False),'<h2>Final manuscript numbers</h2><ul>']
html += [f'<li>{x}</li>' for x in claims]; html += ['</ul>']
for csvp in sorted(T.glob('*.csv')):
    df=pd.read_csv(csvp); html += [f'<h2>{csvp.stem}</h2>',df.to_html(index=False)]
for imgp in sorted(F.glob('*.png')):
    html += [f'<h2>{imgp.stem}</h2>',f'<p>{capmap.get(imgp.stem,"")}</p>',f'<img src="figures/{imgp.name}">']
html += ['<h2>Required interpretation limits</h2><ul>']+[f'<li>{x}</li>' for x in limitations]+['</ul></body></html>']
(O/'EVALUATION_REPORT.html').write_text('\n'.join(html),encoding='utf-8')
print(status); print(G.to_string(index=False))
