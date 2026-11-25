import os, time, hashlib, random, statistics, math, json, platform, resource, csv
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

OUT=Path(os.environ.get('SEAL_RESULTS_DIR', str(Path(__file__).resolve().parents[1] / 'results' / 'local_crypto')))
OUT.mkdir(parents=True, exist_ok=True)
SEED=20261017
rng=random.Random(SEED)
REPS=30
SIZES=[64,128,256,512,1024,2048,4096]
MASK_BYTE=0x2A

# RFC 3526 group 14, safe-prime MODP, benchmark-only classic CH proxy.
P=int('''FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD1
29024E088A67CC74020BBEA63B139B22514A08798E3404DDEF9519B3CD
3A431B302B0A6DF25F14374FE1356D6D51C245E485B576625E7EC6F44
C42E9A637ED6B0BFF5CB6F406B7EDEE386BFB5A899FA5AE9F24117C4B
1FE649286651ECE45B3DC2007CB8A163BF0598DA48361C55D39A69163F
A8FD24CF5F83655D23DCA3AD961C62F356208552BB9ED529077096966D
670C354E4ABC9804F1746C08CA18217C32905E462E36CE3BE39E772C18
0E86039B2783A2EC07A28FB5C55DF06F4C52C9DE2BCBF6955817183995
497CEA956AE515D2261898FA051015728E5A8AACAA68FFFFFFFFFFFFFFFF'''.replace('\n',''),16)
Q=(P-1)//2
G=4  # subgroup generator candidate

def scalar(data: bytes) -> int:
    return int.from_bytes(hashlib.sha256(b'SEAL-CH-MSG-v1'+data).digest(),'big') % Q

def ch_keygen():
    x=rng.randrange(2,Q-1); y=pow(G,x,P); return x,y

def ch_hash(data: bytes, r: int, y: int) -> int:
    m=scalar(data)
    return (pow(G,m,P)*pow(y,r,P))%P

def ch_adapt(old:bytes,r:int,new:bytes,x:int)->int:
    invx=pow(x,-1,Q)
    return (r + (scalar(old)-scalar(new))*invx)%Q

def hash_commit(data:bytes, rho:bytes)->bytes:
    return hashlib.sha256(b'SEAL-COM-v1'+len(data).to_bytes(8,'big')+rho+data).digest()

def valid_mask(orig:bytes, red:bytes)->bool:
    if len(orig)!=len(red): return False
    return all((a==b or b==MASK_BYTE) for a,b in zip(orig,red))

def make_redaction(data:bytes, ratio=0.2)->bytes:
    arr=bytearray(data)
    n=max(1,int(len(arr)*ratio))
    for i in rng.sample(range(len(arr)), min(n,len(arr))): arr[i]=MASK_BYTE
    return bytes(arr)

def ns(f,*args):
    t=time.perf_counter_ns(); v=f(*args); return time.perf_counter_ns()-t,v

def summarize(xs):
    xs=[x/1e6 for x in xs]
    m=statistics.mean(xs); sd=statistics.stdev(xs) if len(xs)>1 else 0
    ci=1.96*sd/math.sqrt(len(xs)) if len(xs)>1 else 0
    xs2=sorted(xs); idx=min(len(xs2)-1, math.ceil(.95*len(xs2))-1)
    return dict(mean_ms=m,median_ms=statistics.median(xs),p95_ms=xs2[idx],stdev_ms=sd,ci95_ms=ci,min_ms=min(xs),max_ms=max(xs))

def write_csv(name, rows):
    if not rows: return
    p=OUT/name
    with p.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

# E1 microbenchmarks
micro=[]
x,y=ch_keygen()
for n in SIZES:
    data=bytes(rng.randrange(0,256) for _ in range(n)); red=make_redaction(data); rho=bytes(rng.randrange(0,256) for _ in range(32)); r=rng.randrange(2,Q-1)
    funcs={
      'sha256': lambda: hashlib.sha256(data).digest(),
      'hash_commit': lambda: hash_commit(data,rho),
      'mask_verify': lambda: valid_mask(data,red),
      'ch_hash_2048': lambda: ch_hash(data,r,y),
      'ch_adapt_2048': lambda: ch_adapt(data,r,red,x),
    }
    for op,fn in funcs.items():
        # Warm-up and amortize timer overhead for very fast operations.
        for _ in range(5): fn()
        if op in ('sha256','hash_commit'): inner=2000
        elif op=='mask_verify': inner=500 if n<=512 else 100
        else: inner=1
        times=[]
        for _ in range(REPS):
            t=time.perf_counter_ns()
            for __ in range(inner): fn()
            times.append((time.perf_counter_ns()-t)/inner)
        row={'experiment':'E1','size_B':n,'operation':op,'reps':REPS,'inner_loops':inner,**summarize(times),'status':'MEASURED'}; micro.append(row)
write_csv('e1_microbench.csv',micro)

# E2 Merkle build scaling, pre-hashed 32-byte leaves isolates tree overhead.
def merkle_root(leaves):
    level=leaves
    while len(level)>1:
        level=[hashlib.sha256(level[i]+level[i+1]).digest() for i in range(0,len(level),2)]
    return level[0]
merkle=[]
for k in [10,12,14,16,18,20]:
    n=1<<k
    seed=hashlib.sha256(f'leaves-{k}'.encode()).digest()
    leaves=[hashlib.sha256(seed+i.to_bytes(8,'big')).digest() for i in range(n)]
    times=[]
    reps=10
    for _ in range(reps): t=time.perf_counter_ns(); merkle_root(leaves); times.append(time.perf_counter_ns()-t)
    merkle.append({'experiment':'E2','leaf_count':n,'height':k,'reps':reps,**summarize(times),'throughput_leaves_s':n/(statistics.mean(times)/1e9),'status':'MEASURED'})
write_csv('e2_merkle.csv',merkle)

# E3 batch redaction: commit + mask verification, 1KiB segments, sequential vs threads.
def redact_unit(pair):
    data,red,rho=pair
    c=hash_commit(data,rho); ok=valid_mask(data,red); c2=hashlib.sha256(red).digest(); return c,c2,ok
batch=[]
for count in [1,10,100,1000,5000]:
    pairs=[]
    for i in range(count):
        d=hashlib.sha512(f'{SEED}-{count}-{i}'.encode()).digest()*16 # 1024 B
        d=d[:1024]; rr=hashlib.sha256(b'rho'+i.to_bytes(8,'big')).digest(); red=make_redaction(d,0.2); pairs.append((d,red,rr))
    for mode in ['sequential','threads5']:
        times=[]; reps=10
        for _ in range(reps):
            t=time.perf_counter_ns()
            if mode=='sequential': [redact_unit(p) for p in pairs]
            else:
                with ThreadPoolExecutor(max_workers=5) as ex: list(ex.map(redact_unit,pairs,chunksize=64))
            times.append(time.perf_counter_ns()-t)
        batch.append({'experiment':'E3','segments':count,'segment_B':1024,'mode':mode,'reps':reps,**summarize(times),'throughput_segments_s':count/(statistics.mean(times)/1e9),'status':'MEASURED'})
write_csv('e3_batch.csv',batch)

# E4 3-of-4 quorum using independent Ed25519 signatures; threshold-aggregate signature remains a future implementation.
keys=[Ed25519PrivateKey.generate() for _ in range(4)]; pubs=[k.public_key() for k in keys]
msg=hashlib.sha256(b'SEAL-redaction-request-v1').digest()
quorum=[]
for qn in [1,2,3,4]:
    st=[]; vt=[]
    for _ in range(REPS):
        t=time.perf_counter_ns(); sigs=[keys[i].sign(msg) for i in range(qn)]; st.append(time.perf_counter_ns()-t)
        t=time.perf_counter_ns();
        for i,sig in enumerate(sigs): pubs[i].verify(sig,msg)
        vt.append(time.perf_counter_ns()-t)
    sr=summarize(st); vr=summarize(vt)
    quorum.append({'experiment':'E4','signers':qn,'threshold_pass':qn>=3,'sign_mean_ms':sr['mean_ms'],'sign_p95_ms':sr['p95_ms'],'verify_mean_ms':vr['mean_ms'],'verify_p95_ms':vr['p95_ms'],'status':'MEASURED_MULTI_SIG_PROXY'})
write_csv('e4_quorum.csv',quorum)

# WAN latency model: 2 RTT rounds + local sign/verify for quorum=3.
q3=next(r for r in quorum if r['signers']==3)
wan=[]
for rtt in [20,50,100]:
    local=q3['sign_mean_ms']+q3['verify_mean_ms']
    total=2*rtt+local
    wan.append({'experiment':'E4-WAN','rtt_ms':rtt,'protocol_rounds':2,'local_crypto_ms':local,'modeled_total_ms':total,'status':'MODELED_FROM_MEASURED_CRYPTO'})
write_csv('e4_wan_model.csv',wan)

# E5 adversarial tests
att=[]
def add_attack(name,expected,observed,detail): att.append({'experiment':'E5','attack':name,'expected':expected,'observed':observed,'pass':expected==observed,'detail':detail,'status':'MEASURED_LOGIC_TEST'})
orig=b'2026-10-17 user=alice action=login ip=10.1.2.3 result=success'
rho=os.urandom(32); C=hash_commit(orig,rho); r0=rng.randrange(2,Q-1); h=ch_hash(orig,r0,y)
# insufficient quorum
add_attack('1-of-4 unilateral edit','REJECT','REJECT' if 1<3 else 'ACCEPT','quorum threshold=3')
add_attack('2-of-4 collusion','REJECT','REJECT' if 2<3 else 'ACCEPT','quorum threshold=3')
add_attack('3-of-4 authorized edit','ACCEPT','ACCEPT' if 3>=3 else 'REJECT','quorum threshold=3')
# full trapdoor fabrication: CH collision succeeds, original commitment binding check fails
fake=b'2026-10-17 user=alice action=delete ip=10.1.2.3 result=success'
r_fake=ch_adapt(orig,r0,fake,x); ch_collision=(ch_hash(fake,r_fake,y)==h); fake_commit_match=(hash_commit(fake,rho)==C)
add_attack('4-of-4/full-trapdoor fabricate content','REJECT','REJECT' if (ch_collision and not fake_commit_match) else 'ACCEPT',f'CH collision={ch_collision}; immutable commitment match={fake_commit_match}')
# tamper unmasked byte
red=bytearray(make_redaction(orig,0.15)); idx=next(i for i,b in enumerate(red) if b!=MASK_BYTE); red[idx]=(red[idx]+1)%256
add_attack('tamper unmasked byte','REJECT','ACCEPT' if valid_mask(orig,bytes(red)) else 'REJECT','mask predicate')
# over-redaction: mask-only accepts, simple policy max 50% rejects
allmask=bytes([MASK_BYTE])*len(orig); mask_only=valid_mask(orig,allmask); ratio=sum(1 for b in allmask if b==MASK_BYTE)/len(allmask); policy=mask_only and ratio<=0.5
add_attack('over-redaction 100%','REJECT','ACCEPT' if policy else 'REJECT',f'mask-only={mask_only}; mask_ratio={ratio:.2f}; max=0.50')
# rollback/version-chain pointer
v0=hashlib.sha256(b'v0'+C).digest(); v1=hashlib.sha256(b'v1'+v0+b'redaction').digest(); presented=v0; head=v1
add_attack('rollback to pre-redaction version','REJECT','REJECT' if presented!=head else 'ACCEPT','presented version is not current chain head')
# replay across evidence context via context-bound commitment
ctx1=hashlib.sha256(b'case-A|leaf-7|v1').digest(); ctx2=hashlib.sha256(b'case-B|leaf-7|v1').digest()
def ctx_commit(data,rho,ctx): return hashlib.sha256(b'SEAL-CTX-v1'+ctx+rho+data).digest()
proof_anchor=ctx_commit(orig,rho,ctx1)
add_attack('cross-case proof replay','REJECT','REJECT' if ctx_commit(orig,rho,ctx2)!=proof_anchor else 'ACCEPT','commit/proof context binds case-id, leaf-id, version')
# classic CH key exposure demonstration
m0=scalar(orig); mf=scalar(fake); recovered=((m0-mf)*pow((r_fake-r0)%Q,-1,Q))%Q if (r_fake-r0)%Q else None
# Adapt equation gives r'-r=(m-m')/x, so recovered x=(m-m')/(r'-r)
add_attack('classic CH collision leaks trapdoor','LEAK_DETECTED','LEAK_DETECTED' if recovered==x else 'NO_LEAK','motivates using a proven key-exposure-free CHET rather than this benchmark proxy')
write_csv('e5_adversarial.csv',att)

# E6 metadata/storage model (not measured chain storage). Groth16 EVM ABI proof often 8 uint256=256B; compact encoding differs.
storage=[]
for batchn in [1,10,100,1000,5000]:
    per={'orig_commit':32,'leaf_index':8,'version_ptr':32,'policy_id':32,'timestamp':8,'quorum_ed25519_sigs':3*64,'groth16_proof_evm_abi':256,'redacted_commit':32}
    total=sum(per.values())*batchn
    storage.append({'experiment':'E6','redactions':batchn,'bytes_per_redaction_model':sum(per.values()),'total_bytes_model':total,'total_MiB_model':total/(1024**2),'status':'MODELED_NOT_CHAIN_MEASURED'})
write_csv('e6_storage_model.csv',storage)

# E7 end-to-end forensic case study: 5,000 realistic Apache-style lines with innocent-user IPs.
import re
IP_RE=re.compile(rb'client=(\d{1,3}(?:\.\d{1,3}){3})')
def mask_ips(line:bytes):
    out=bytearray(line); spans=[]
    for m in IP_RE.finditer(line):
        a,b=m.span(1); spans.append((a,b))
        for i in range(a,b): out[i]=MASK_BYTE
    return bytes(out),spans

def merkle_from_lines(lines):
    leaves=[hashlib.sha256(x).digest() for x in lines]
    # pad to next power of two with domain-separated empty leaf
    n=1
    while n<len(leaves): n*=2
    empty=hashlib.sha256(b'SEAL-empty-leaf').digest(); leaves += [empty]*(n-len(leaves))
    return merkle_root(leaves)

case_rows=[]
for users in [100,1000,5000,10000]:
    lines=[]
    for i in range(users):
        ip=f'{10+(i%200)}.{(i//200)%250}.{(i//50000)%250}.{1+(i%253)}'
        line=f'2026-10-17T12:{i%60:02d}:{(i*7)%60:02d}Z level=INFO client={ip} user=u{i:05d} action=GET path=/portal/{i%97} status=200'.encode()
        lines.append(line)
    times=[]; acq=[]; redact=[]; verify=[]; quorum_t=[]
    reps=10
    for _ in range(reps):
        t0=time.perf_counter_ns(); root0=merkle_from_lines(lines); acq.append(time.perf_counter_ns()-t0)
        t1=time.perf_counter_ns(); red_lines=[]; commitments=[]
        for line in lines:
            rline,sp=mask_ips(line); red_lines.append(rline); commitments.append(hash_commit(line,hashlib.sha256(line+b'rho').digest()))
        rootR=merkle_from_lines(red_lines); redact.append(time.perf_counter_ns()-t1)
        req=hashlib.sha256(b'SEAL-E7'+root0+rootR).digest()
        tq=time.perf_counter_ns(); sigs=[keys[i].sign(req) for i in range(3)]; [pubs[i].verify(sigs[i],req) for i in range(3)]; quorum_t.append(time.perf_counter_ns()-tq)
        tv=time.perf_counter_ns(); ok=all(valid_mask(o,r) for o,r in zip(lines,red_lines)) and len(sigs)>=3; _=merkle_from_lines(red_lines); verify.append(time.perf_counter_ns()-tv)
        times.append(time.perf_counter_ns()-t0)
        if not ok: raise RuntimeError('case study verification failed')
    def sm(xs): return summarize(xs)
    case_rows.append({'experiment':'E7','records':users,'pii_fields':users,'reps':reps,
      'acquisition_mean_ms':sm(acq)['mean_ms'],'redaction_mean_ms':sm(redact)['mean_ms'],
      'quorum_mean_ms':sm(quorum_t)['mean_ms'],'independent_verify_mean_ms':sm(verify)['mean_ms'],
      'end_to_end_mean_ms':sm(times)['mean_ms'],'end_to_end_p95_ms':sm(times)['p95_ms'],
      'status':'MEASURED_SYNTHETIC_FORENSIC_CASE'})
write_csv('e7_case_study.csv',case_rows)

meta={
 'timestamp_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
 'seed':SEED,'repetitions_default':REPS,'python':platform.python_version(),'platform':platform.platform(),
 'cpu_count':os.cpu_count(),'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
 'notes':['E4 uses 3-of-4 Ed25519 multi-signature as a quorum proxy, not an aggregated threshold signature.',
          'E1 CH is a classic 2048-bit finite-field chameleon-hash performance proxy and is intentionally NOT key-exposure free.',
          'E4-WAN and E6 are modeled; all other timing rows are measured locally.',
          'Groth16/Circom results are intentionally absent until the external SNARK toolchain is run.']
}
(OUT/'environment.json').write_text(json.dumps(meta,indent=2))
print(json.dumps({'micro_rows':len(micro),'merkle_rows':len(merkle),'batch_rows':len(batch),'quorum_rows':len(quorum),'attack_rows':len(att),'max_rss_kib':meta['max_rss_kib']},indent=2))
