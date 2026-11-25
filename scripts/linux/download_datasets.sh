#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="$PROJECT/datasets/public"; mkdir -p "$OUT"
fetch(){
  local url="$1" out="$2" blob="$3"
  if [ ! -s "$out" ]; then curl -fL --retry 5 "$url" -o "$out"; fi
  local got
  got=$(git hash-object "$out")
  if [ "$got" != "$blob" ]; then echo "Dataset Git-blob mismatch for $out: got $got expected $blob" >&2; exit 2; fi
  echo "verified $(basename "$out") git-blob=$got"
}
fetch 'https://raw.githubusercontent.com/logpai/loghub/master/Apache/Apache_2k.log' "$OUT/Apache_2k.log" 'dd8a218ed474579f146960846f45a50f55ca0de0'
fetch 'https://raw.githubusercontent.com/logpai/loghub/master/OpenSSH/OpenSSH_2k.log' "$OUT/OpenSSH_2k.log" '587f66b1ebf40fd59f385addc69a8b0671f34b9c'
