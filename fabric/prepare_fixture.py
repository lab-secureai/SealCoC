#!/usr/bin/env python3
import argparse, json, hashlib
from pathlib import Path
ap=argparse.ArgumentParser()
ap.add_argument('--dir',required=True)
ap.add_argument('--out',required=True)
a=ap.parse_args(); d=Path(a.dir)
inputj=json.loads((d/'input.json').read_text())
pub=json.loads((d/'public_0.json').read_text())
if len(pub)<5: raise SystemExit(f'Expected >=5 public signals, got {len(pub)}')
orig=bytes(inputj['orig']); red=bytes(inputj['red'])
obj={
 'original_sha256':hashlib.sha256(orig).hexdigest(),
 'redacted_sha256':hashlib.sha256(red).hexdigest(),
 'merkle_root':hashlib.sha256(b'SEAL-LEAF-v1'+orig).hexdigest(),
 'original_poseidon':pub[0], 'redacted_poseidon':pub[1],
 'mask_count':pub[2], 'context':pub[3], 'max_mask':pub[4],
 'public_signal_count':len(pub),
 'metadata':json.dumps({'type':'synthetic-log-segment','bytes':len(orig),'purpose':'SEAL-CoC Fabric integration benchmark'},separators=(',',':'))
}
Path(a.out).write_text(json.dumps(obj,indent=2))
print(json.dumps(obj,indent=2))
