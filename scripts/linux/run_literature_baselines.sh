#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="$PROJECT/results/baselines"; SRC="$PROJECT/third_party/blockchain_tests"; mkdir -p "$OUT" "$PROJECT/third_party"
COMMIT='c95c175919667d9383598b200d59e7f17cc1bad2'
export DEBIAN_FRONTEND=noninteractive
apt-get update >/dev/null
apt-get install -y --no-install-recommends libssl-dev libgmp-dev >/dev/null
if [ ! -d "$SRC/.git" ]; then
  rm -rf "$SRC"; mkdir -p "$SRC"; git -C "$SRC" init -q; git -C "$SRC" remote add origin https://github.com/thiagoharry/blockchain_tests.git
fi
git -C "$SRC" fetch -q --depth 1 origin "$COMMIT"; git -C "$SRC" checkout -q --detach FETCH_HEAD
make -C "$SRC" clean >/dev/null 2>&1 || true
make -C "$SRC" regular_blockchain traditional_redactable_blockchain secret_coin_redactable_blockchain > "$OUT/build.log" 2>&1
for exe in blockchain traditional_redactable_blockchain secret_coin_redactable_blockchain; do
  echo "Running $exe ..."
  (cd "$SRC" && ./$exe) | tee "$OUT/${exe}.txt"
done
python3 - "$OUT" "$COMMIT" <<'PYCODE'
import sys,re,csv,pathlib
out=pathlib.Path(sys.argv[1]); commit=sys.argv[2]; rows=[]
mapn={'blockchain':'Double-SHA256 baseline','traditional_redactable_blockchain':'Ateniese traditional CH implementation','secret_coin_redactable_blockchain':'Derler-style secret-coin CH implementation'}
# Parse output line-by-line; this fixes the  parser bug where operation labels could absorb the prior line suffix.
pat=re.compile(r'^\s*(.*?):+\s*([0-9.]+)\s*(?:s|seconds)\s*(?:\(σ=|±|\+/-)\s*([0-9.]+)\s*(?:s|seconds)?\)?\s*$')
for stem,name in mapn.items():
    p=out/(stem+'.txt'); text=p.read_text(errors='ignore') if p.exists() else ''; found=0
    for line in text.splitlines():
        m=pat.match(line)
        if not m: continue
        found+=1
        rows.append({'baseline':name,'operation':m.group(1).strip(),'block_size_B':1048576,'mean_ms':float(m.group(2))*1000,'stdev_ms':float(m.group(3))*1000,'source_commit':commit,'status':'MEASURED_THIRD_PARTY_CODE'})
    if not found:
        rows.append({'baseline':name,'operation':'UNPARSED','block_size_B':1048576,'mean_ms':'','stdev_ms':'','source_commit':commit,'status':'FAILED_TO_PARSE_OUTPUT'})
with (out/'literature_baselines.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
print(*rows,sep='\n')
PYCODE
