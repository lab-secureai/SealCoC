#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$PROJECT/config/config.env"
OUT="$PROJECT/results/evm"; mkdir -p "$OUT"
SDIR="$PROJECT/snark_results/n${FABRIC_CIRCUIT_SIZE}"
SNARK="$PROJECT/node_modules/.bin/snarkjs"
"$SNARK" zkey export solidityverifier "$SDIR/circuit_final.zkey" "$OUT/Groth16Verifier.sol"
"$SNARK" zkey export soliditycalldata "$SDIR/public_0.json" "$SDIR/proof_0.json" > "$OUT/calldata.txt"
node "$PROJECT/evm/benchmark_evm.cjs" "$OUT/Groth16Verifier.sol" "$OUT/calldata.txt" "$OUT/evm_gas.csv"
