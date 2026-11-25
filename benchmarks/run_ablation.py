import time, random, hashlib, csv, statistics, math
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
OUT=Path(__import__('os').environ.get('SEAL_RESULTS_DIR', str(Path(__file__).resolve().parents[1] / 'results' / 'local_crypto'))); OUT.mkdir(exist_ok=True)
rng=random.Random(20261017); REPS=30; MASK=42
P=int('''FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA63B139B22514A08798E3404DDEF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7EDEE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3DC2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F83655D23DCA3AD961C62F356208552BB9ED529077096966D670C354E4ABC9804F1746C08CA18217C32905E462E36CE3BE39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9DE2BCBF6955817183995497CEA956AE515D2261898FA051015728E5A8AACAA68FFFFFFFFFFFFFFFF''',16)
Q=(P-1)//2; G=4
x=rng.randrange(2,Q-1); y=pow(G,x,P); invx=pow(x,-1,Q)
keys=[Ed25519PrivateKey.generate() for _ in range(4)]; pubs=[k.public_key() for k in keys]

def scalar(d): return int.from_bytes(hashlib.sha256(b'CH'+d).digest(),'big')%Q
def ch(d,r): return pow(G,scalar(d),P)*pow(y,r,P)%P
def adapt(o,r,n): return (r+(scalar(o)-scalar(n))*invx)%Q
def commit(d,rho): return hashlib.sha256(b'COM'+rho+d).digest()
def maskok(o,n): return len(o)==len(n) and all(a==b or b==MASK for a,b in zip(o,n))
def redact(d):
 b=bytearray(d)
 for i in rng.sample(range(len(b)),max(1,len(b)//5)): b[i]=MASK
 return bytes(b)
def summ(v):
 ms=[x/1e6 for x in v]; ms.sort(); return statistics.mean(ms),statistics.median(ms),ms[math.ceil(.95*len(ms))-1]

rows=[]
for N in [64,1024,4096]:
 o=bytes(rng.randrange(0,256) for _ in range(N)); n=redact(o); r=rng.randrange(2,Q-1); h=ch(o,r); rho=hashlib.sha256(b'rho'+N.to_bytes(4,'big')).digest(); msg=hashlib.sha256(b'req'+h.to_bytes(256,'big')).digest()
 def sha_only(): return hashlib.sha256(n).digest()
 def ch_only():
  rp=adapt(o,r,n); assert ch(n,rp)==h
 def ch_quorum():
  rp=adapt(o,r,n); assert ch(n,rp)==h
  sig=[keys[i].sign(msg) for i in range(3)]
  for i,s in enumerate(sig): pubs[i].verify(s,msg)
 def seal_no_snark():
  rp=adapt(o,r,n); assert ch(n,rp)==h; c0=commit(o,rho); c1=commit(n,rho); assert c0!=c1 and maskok(o,n)
  sig=[keys[i].sign(msg) for i in range(3)]
  for i,s in enumerate(sig): pubs[i].verify(s,msg)
 for label,fn,status in [('SHA-256 immutable baseline',sha_only,'MEASURED'),('CH redactable proxy',ch_only,'MEASURED_CH_PROXY'),('CH + 3/4 quorum proxy',ch_quorum,'MEASURED_CH_AND_MULTISIG_PROXY'),('SEAL core without SNARK',seal_no_snark,'MEASURED_PRE_SNARK')]:
  for _ in range(3): fn()
  ts=[]
  for _ in range(REPS): t=time.perf_counter_ns();fn();ts.append(time.perf_counter_ns()-t)
  mean,med,p95=summ(ts);rows.append({'experiment':'E8','size_B':N,'configuration':label,'reps':REPS,'mean_ms':mean,'median_ms':med,'p95_ms':p95,'status':status})
 rows.append({'experiment':'E8','size_B':N,'configuration':'Full SEAL-CoC incl. Groth16','reps':0,'mean_ms':'','median_ms':'','p95_ms':'','status':'PENDING_REAL_SNARK_RUN'})
with open(OUT/'e8_ablation.csv','w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
print(*rows,sep='\n')
