#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$PROJECT/config/config.env"
mkdir -p "$PROJECT/results/logs" "$PROJECT/artifacts" "$PROJECT/third_party"
LOG="$PROJECT/results/logs/full_run_$(date -u +%Y%m%dT%H%M%SZ).log"
exec > >(tee -a "$LOG") 2>&1
WINDOWS_RESULTS="${SEAL_WINDOWS_RESULTS:-}"
progress(){
  local phase="$1"; shift
  local msg="$*"
  local line="$(date -u +%FT%TZ) | ${phase} | ${msg}"
  echo "$line" | tee "$PROJECT/results/progress.txt" >/dev/null
  if [ -n "$WINDOWS_RESULTS" ]; then
    mkdir -p "$WINDOWS_RESULTS" 2>/dev/null || true
    echo "$line" > "$WINDOWS_RESULTS/progress.txt" 2>/dev/null || true
  fi
  echo "==> [$phase] $msg"
}
trap 'rc=$?; progress FAILED "line $LINENO: command failed: $BASH_COMMAND (exit=$rc)"; exit $rc' ERR

progress START "SEAL-CoC full reproducible experiment"
echo "UTC start: $(date -u +%FT%TZ)"
echo "Project: $PROJECT"

export DEBIAN_FRONTEND=noninteractive
progress PREREQS "Installing Ubuntu packages and Docker"
apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates curl git jq unzip zip build-essential gcc g++ make cmake \
  python3 python3-venv python3-pip nodejs npm golang-go \
  docker.io docker-compose-v2 libgmp-dev libsodium-dev nasm m4 bc time

if command -v systemctl >/dev/null 2>&1; then
  systemctl enable --now docker || true
fi
service docker start || true
for i in {1..30}; do docker info >/dev/null 2>&1 && break; sleep 2; done
docker info >/dev/null

progress DOCKER "Docker is running; recording tool versions"
echo "== Versions before project setup =="
uname -a
python3 --version
node --version
npm --version
go version
docker --version
docker compose version

if [ ! -d "$PROJECT/.venv" ]; then python3 -m venv "$PROJECT/.venv"; fi
source "$PROJECT/.venv/bin/activate"
pip install --upgrade pip wheel
pip install cryptography pandas matplotlib psutil tabulate

cd "$PROJECT"
npm install --no-audit --no-fund

ARCH="$(uname -m)"
if [ "$ARCH" != "x86_64" ] && [ "$ARCH" != "amd64" ]; then
  echo "This one-click bundle currently pins the official Circom amd64 binary; detected $ARCH." >&2
  exit 4
fi
progress CIRCOM "Installing/checking Circom and SnarkJS"
if ! command -v circom >/dev/null 2>&1 || ! circom --version 2>/dev/null | grep -q "$CIRCOM_VERSION"; then
  echo "Installing Circom $CIRCOM_VERSION"
  curl -fL --retry 5 -o /usr/local/bin/circom "https://github.com/iden3/circom/releases/download/v${CIRCOM_VERSION}/circom-linux-amd64"
  chmod +x /usr/local/bin/circom
fi
circom --version
npx snarkjs --version || true

progress PTAU "Preparing Powers of Tau cache (power=$PTAU_POWER)"
PTAU="$PROJECT/artifacts/pot${PTAU_POWER}_final.ptau"
if [ ! -s "$PTAU" ]; then
  echo "Generating local Powers of Tau (power=$PTAU_POWER); cached for future runs."
  npx snarkjs powersoftau new bn128 "$PTAU_POWER" "$PROJECT/artifacts/pot${PTAU_POWER}_0000.ptau" -v
  npx snarkjs powersoftau contribute "$PROJECT/artifacts/pot${PTAU_POWER}_0000.ptau" "$PROJECT/artifacts/pot${PTAU_POWER}_0001.ptau" --name="SEAL-CoC local benchmark" -e="SEAL-CoC-PoT-20261017"
  npx snarkjs powersoftau prepare phase2 "$PROJECT/artifacts/pot${PTAU_POWER}_0001.ptau" "$PTAU" -v
fi

progress FABRIC_INSTALL "Installing/checking Hyperledger Fabric $FABRIC_VERSION + CA $FABRIC_CA_VERSION"
FABRIC_HOME="$PROJECT/third_party/fabric-samples"
if [ ! -x "$FABRIC_HOME/bin/peer" ]; then
  echo "Installing Hyperledger Fabric $FABRIC_VERSION and CA $FABRIC_CA_VERSION"
  cd "$PROJECT/third_party"
  curl -fL --retry 5 -o install-fabric.sh https://raw.githubusercontent.com/hyperledger/fabric/main/scripts/install-fabric.sh
  chmod +x install-fabric.sh
  ./install-fabric.sh --fabric-version "$FABRIC_VERSION" --ca-version "$FABRIC_CA_VERSION" docker binary samples
fi
export PATH="$FABRIC_HOME/bin:$PATH"
export FABRIC_CFG_PATH="$FABRIC_HOME/config"
peer version || true

# Resolve and vendor chaincode dependencies before deployment for reproducibility.
cd "$PROJECT/chaincode/sealcoc"
go mod tidy
go mod vendor
go test ./... || true

progress LOCAL "Stage 1/5: local crypto, adversarial tests, ablation"
echo "== Stage 1: local crypto/adversarial/ablation =="
export SEAL_RESULTS_DIR="$PROJECT/results/local_crypto"
mkdir -p "$SEAL_RESULTS_DIR"
python "$PROJECT/benchmarks/run_local_crypto.py"
python "$PROJECT/benchmarks/run_ablation.py"

progress SNARK "Stage 2/5: Groth16 benchmark 64 B to 4 KiB"
echo "== Stage 2: Groth16 benchmark 64 B -> 4 KiB =="
"$PROJECT/scripts/linux/run_snark.sh" "$PTAU"

progress FABRIC "Stage 3/5: Fabric network + embedded Groth16 verification"
echo "== Stage 3: Fabric network + embedded Groth16 verification =="
"$PROJECT/scripts/linux/run_fabric.sh"

if [ "$RUN_EVM" = "1" ]; then
  progress EVM "Stage 4/5: local EVM Groth16 verifier gas benchmark"
  echo "== Stage 4: local EVM Groth16 verifier gas benchmark =="
  "$PROJECT/scripts/linux/run_evm.sh"
fi

progress AGGREGATE "Stage 5/5: aggregating paper-ready tables"
echo "== Stage 5: aggregate paper-ready tables =="
python "$PROJECT/benchmarks/aggregate_results.py"
"$PROJECT/scripts/linux/capture_environment.sh"

echo "UTC end: $(date -u +%FT%TZ)"
progress DONE "All experiment stages completed; results at $PROJECT/results"
echo "All results: $PROJECT/results"
