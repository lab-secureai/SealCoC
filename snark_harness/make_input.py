import json, hashlib, random, sys
N=int(sys.argv[1]); out=sys.argv[2]
P=21888242871839275222246405745257275088548364400416034343698204186575808495617
rng=random.Random(20261017+N)
orig=[rng.randrange(32,127) for _ in range(N)]
mask=[0]*N
for i in rng.sample(range(N), max(1,N//5)): mask[i]=1
red=[42 if mask[i] else orig[i] for i in range(N)]
def fld(tag): return str(int.from_bytes(hashlib.sha256((tag+str(N)).encode()).digest(),'big')%P)
obj={
 'orig':orig,'red':red,'mask':mask,
 'rhoOrig':fld('rhoO'),'rhoRed':fld('rhoR'),
 'context':fld('case-A|leaf-7|v1|'),
 'maxMask':str(N//2)
}
open(out,'w').write(json.dumps(obj))
