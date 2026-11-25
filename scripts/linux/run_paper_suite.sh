#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT=/root/seal-coc
WINDOWS_RESULTS="${1:-}"
cd "$PROJECT"
source "$PROJECT/config/config.env"
mkdir -p "$PROJECT/results/logs"
LOG="$PROJECT/results/logs/paper_suite_$(date -u +%Y%m%dT%H%M%SZ).log"
exec > >(tee -a "$LOG") 2>&1
progress(){
  local phase="$1"; shift; local msg="$*"; local line="$(date -u +%FT%TZ) | $phase | $msg"
  echo "$line" > "$PROJECT/results/progress.txt"; [ -n "$WINDOWS_RESULTS" ] && { mkdir -p "$WINDOWS_RESULTS"; echo "$line" > "$WINDOWS_RESULTS/progress.txt"; } || true
  echo "==> [$phase] $msg"
}
trap 'rc=$?; progress FAILED "line $LINENO: $BASH_COMMAND (exit=$rc)"; exit $rc' ERR

progress CHECK "Preparing paper evaluation suite; preserving existing measured results"
export DEBIAN_FRONTEND=noninteractive
apt-get update >/dev/null
apt-get install -y --no-install-recommends ca-certificates curl git jq build-essential gcc g++ make python3 python3-venv python3-pip nodejs npm golang-go docker.io docker-compose-v2 libgmp-dev libssl-dev libsodium-dev bc time iproute2 util-linux >/dev/null
service docker start >/dev/null 2>&1 || true
for i in {1..30}; do docker info >/dev/null 2>&1 && break; sleep 2; done
docker info >/dev/null

if [ ! -x "$PROJECT/.venv/bin/python" ]; then python3 -m venv "$PROJECT/.venv"; fi
source "$PROJECT/.venv/bin/activate"
python -m pip install --disable-pip-version-check --no-input -U pip wheel >/dev/null
python -m pip install --disable-pip-version-check --no-input cryptography pandas matplotlib psutil tabulate jinja2 >/dev/null

progress NODE "Checking pinned Node/SnarkJS dependencies"
if [ ! -x "$PROJECT/node_modules/.bin/snarkjs" ]; then (cd "$PROJECT" && npm install --no-audit --no-fund); fi

progress CIRCOM "Checking Circom $CIRCOM_VERSION"
if ! command -v circom >/dev/null 2>&1 || ! circom --version 2>/dev/null | grep -q "$CIRCOM_VERSION"; then
  curl -fL --retry 5 -o /usr/local/bin/circom "https://github.com/iden3/circom/releases/download/v${CIRCOM_VERSION}/circom-linux-amd64"; chmod +x /usr/local/bin/circom
fi
circom --version

progress PTAU "Checking Powers of Tau cache"
PTAU="$PROJECT/artifacts/pot${PTAU_POWER}_final.ptau"; mkdir -p "$PROJECT/artifacts"
if [ ! -s "$PTAU" ]; then
  npx snarkjs powersoftau new bn128 "$PTAU_POWER" "$PROJECT/artifacts/pot${PTAU_POWER}_0000.ptau" -v
  npx snarkjs powersoftau contribute "$PROJECT/artifacts/pot${PTAU_POWER}_0000.ptau" "$PROJECT/artifacts/pot${PTAU_POWER}_0001.ptau" --name="SEAL-CoC paper benchmark" -e="SEAL-CoC-PoT-20261017"
  npx snarkjs powersoftau prepare phase2 "$PROJECT/artifacts/pot${PTAU_POWER}_0001.ptau" "$PTAU" -v
fi

progress FABRIC_INSTALL "Checking Hyperledger Fabric $FABRIC_VERSION"
FABRIC_HOME="$PROJECT/third_party/fabric-samples"
if [ ! -x "$FABRIC_HOME/bin/peer" ]; then
  mkdir -p "$PROJECT/third_party"; cd "$PROJECT/third_party"
  curl -fL --retry 5 -o install-fabric.sh https://raw.githubusercontent.com/hyperledger/fabric/main/scripts/install-fabric.sh; chmod +x install-fabric.sh
  ./install-fabric.sh --fabric-version "$FABRIC_VERSION" --ca-version "$FABRIC_CA_VERSION" docker binary samples
  cd "$PROJECT"
fi
export PATH="$FABRIC_HOME/bin:$PATH"; export FABRIC_CFG_PATH="$FABRIC_HOME/config"

progress LOCAL "Research question 4/Research question 5 local primitives, Merkle, batch, security, case study and ablation"
export SEAL_RESULTS_DIR="$PROJECT/results/local_crypto"; mkdir -p "$SEAL_RESULTS_DIR"
python "$PROJECT/benchmarks/run_local_crypto.py"
python "$PROJECT/benchmarks/run_ablation.py"

progress SNARK_BASE "Research question 1 base Groth16 scaling 64 B–4 KiB"
need_snark=0
if [ ! -s "$PROJECT/results/snark/snark_bench.csv" ]; then need_snark=1; fi
for N in ${SNARK_SIZES//,/ }; do [ -s "$PROJECT/snark_results/n$N/circuit_final.zkey" ] || need_snark=1; done
if [ "$need_snark" = 1 ]; then "$PROJECT/scripts/linux/run_snark.sh" "$PTAU"; else echo "Reusing complete base Groth16 measurements/artifacts."; fi

progress SNARK_RATIO "Research question 1 mask-ratio sensitivity"
python "$PROJECT/snark_harness/bench_mask_ratio.py" --root "$PROJECT" --snarkjs "$PROJECT/node_modules/.bin/snarkjs" --reps "$SNARK_MASK_RATIO_REPS"

progress DATASETS "Research question 4 public Loghub and user-supplied forensic artifacts"
"$PROJECT/scripts/linux/download_datasets.sh"
DATASET_REPS="$DATASET_REPS" FORENSIC_MAX_BYTES="$FORENSIC_MAX_BYTES" python "$PROJECT/benchmarks/run_dataset_cases.py"

if [ "${RUN_LITERATURE_BASELINES:-1}" = 1 ]; then
  progress BASELINES "Research question 5 reproducing pinned public redactable-blockchain baseline code"
  if ! "$PROJECT/scripts/linux/run_literature_baselines.sh"; then
    echo "WARNING: third-party baseline reproduction failed; paper generator will mark it missing/optional." >&2
  fi
fi

progress FABRIC_PAPER "Research question 2/Research question 3 extended Fabric experiments: size, throughput, quorum, storage, attacks, WAN, true E2E"
FABRIC_PAPER_VERIFY_REPS="$FABRIC_PAPER_VERIFY_REPS" FABRIC_PAPER_SUBMIT_REPS="$FABRIC_PAPER_SUBMIT_REPS" FABRIC_PAPER_FLOW_REPS="$FABRIC_PAPER_FLOW_REPS" \
FABRIC_PAPER_THROUGHPUT_TX="$FABRIC_PAPER_THROUGHPUT_TX" FABRIC_PAPER_CONCURRENCIES="$FABRIC_PAPER_CONCURRENCIES" FABRIC_PAPER_E2E_REPS="$FABRIC_PAPER_E2E_REPS" FABRIC_PAPER_WAN_REPS="$FABRIC_PAPER_WAN_REPS" \
  "$PROJECT/scripts/linux/run_fabric_paper.sh"

progress EVM "Research question 5 local EVM verifier gas"
"$PROJECT/scripts/linux/run_evm.sh"

progress AGGREGATE "Building legacy summary plus paper-ready tables/figures/narrative"
python "$PROJECT/benchmarks/aggregate_results.py"
python "$PROJECT/benchmarks/generate_paper_ready.py"
"$PROJECT/scripts/linux/capture_environment.sh" || true
# Regenerate once after environment capture so completeness sees environment.txt.
python "$PROJECT/benchmarks/generate_paper_ready.py"

progress EXPORT "Copying raw and paper-ready results to Windows"
if [ -n "$WINDOWS_RESULTS" ]; then
  mkdir -p "$WINDOWS_RESULTS"; cp -R "$PROJECT/results/." "$WINDOWS_RESULTS/"
fi
progress DONE "Paper suite complete. Open results/paper_ready/README_PAPER_READY.md"
