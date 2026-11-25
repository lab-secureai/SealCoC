#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT=/root/seal-coc; WINRES="${1:-}"; cd "$PROJECT"; source "$PROJECT/config/config.env"
mkdir -p "$PROJECT/results/logs" "$PROJECT/results/final_validation" "$PROJECT/results/final_report"
LOG="$PROJECT/results/logs/final_report_validation_$(date -u +%Y%m%dT%H%M%SZ).log"
exec > >(tee -a "$LOG") 2>&1
progress(){ local phase="$1"; shift; local line="$(date -u +%FT%TZ) | $phase | $*"; echo "$line" > "$PROJECT/results/progress.txt"; [ -n "$WINRES" ] && { mkdir -p "$WINRES"; echo "$line" > "$WINRES/progress.txt"; } || true; echo "==> [$phase] $*"; }
trap 'rc=$?; progress FAILED "line $LINENO: $BASH_COMMAND (exit=$rc)"; exit $rc' ERR
progress CHECK "Final validation: verifying prior foundational results and dependencies"
for f in "$PROJECT/results/snark/snark_bench.csv" "$PROJECT/results/fabric_paper/f6_adversarial.csv" "$PROJECT/results/local_crypto/e5_adversarial.csv"; do [ -s "$f" ] || { echo "Missing prior result: $f. Run the paper experiment suite first." >&2; exit 20; }; done
export DEBIAN_FRONTEND=noninteractive
apt-get update >/dev/null
apt-get install -y --no-install-recommends ca-certificates curl git jq build-essential gcc g++ make python3 python3-venv python3-pip docker.io docker-compose-v2 libgmp-dev libssl-dev bc time iproute2 util-linux iputils-ping e2fsprogs zip >/dev/null
service docker start >/dev/null 2>&1 || true
for i in {1..30}; do docker info >/dev/null 2>&1 && break; sleep 2; done
docker info >/dev/null
source "$PROJECT/.venv/bin/activate"
python -m pip install --disable-pip-version-check --no-input pandas matplotlib tabulate jinja2 psutil cryptography pycryptodome ecdsa >/dev/null
progress DATASETS "Adding real network-flow and binary-artifact modality experiments"
"$PROJECT/scripts/linux/prepare_final_datasets.sh"
DATASET_REPS="$DATASET_REPS" FINAL_NETWORK_DATASET_MAX_BYTES="$FINAL_NETWORK_DATASET_MAX_BYTES" python "$PROJECT/benchmarks/run_final_dataset_cases.py"
progress BASELINE_CLASSIC "Re-running pinned public classic redactable-blockchain baselines with corrected parser"
"$PROJECT/scripts/linux/run_literature_baselines.sh"
progress BASELINE_THRESHOLD "Reproducing modern TPCH-repository 3-of-4 threshold TCH core"
"$PROJECT/scripts/linux/run_modern_threshold_baseline.sh"
progress FABRIC "Final reviewer-grade Fabric validation; expect roughly 25–45 minutes on a laptop"
"$PROJECT/scripts/linux/run_fabric_final_validation.sh"
progress GENERATE "Generating final LaTeX tables, publication figures, confidence intervals, and quality gates"
python "$PROJECT/benchmarks/generate_final_report.py"
"$PROJECT/scripts/linux/capture_environment.sh" || true
python "$PROJECT/benchmarks/generate_final_report.py"
progress PACKAGE "Creating a compact final package"
rm -f "$PROJECT/results/EVALUATION_PACKAGE.zip"
(cd "$PROJECT/results" && zip -qr EVALUATION_PACKAGE.zip final_report final_validation environment.txt snark fabric_paper local_crypto baselines datasets 2>/dev/null || zip -qr EVALUATION_PACKAGE.zip final_report final_validation)
progress EXPORT "Copying final validation outputs back to Windows"
if [ -n "$WINRES" ]; then
  mkdir -p "$WINRES/final_report" "$WINRES/final_validation"
  rm -rf "$WINRES/final_report" "$WINRES/final_validation"; cp -R "$PROJECT/results/final_report" "$WINRES/"; cp -R "$PROJECT/results/final_validation" "$WINRES/"
  cp "$PROJECT/results/EVALUATION_PACKAGE.zip" "$WINRES/EVALUATION_PACKAGE.zip"
fi
progress DONE "Final validation completed. Open results/final_report/SUBMISSION_READINESS.md"
