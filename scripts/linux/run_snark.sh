#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$PROJECT/config/config.env"
source "$PROJECT/.venv/bin/activate"
PTAU="${1:-$PROJECT/artifacts/pot${PTAU_POWER}_final.ptau}"
rm -rf "$PROJECT/snark_results"
python "$PROJECT/snark_harness/bench_snark.py" \
  --circom circom --snarkjs "$PROJECT/node_modules/.bin/snarkjs" \
  --ptau "$PTAU" --reps "$SNARK_REPS" --sizes "$SNARK_SIZES" --root "$PROJECT"
mkdir -p "$PROJECT/results/snark"
cp -a "$PROJECT/snark_results/." "$PROJECT/results/snark/"
