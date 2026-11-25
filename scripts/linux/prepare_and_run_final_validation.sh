#!/usr/bin/env bash
set -Eeuo pipefail
SRC="${1:?Windows-mounted source path required}"; WINRES="${2:-}"; PROJECT=/root/seal-coc
[ -f "$SRC/circuits/valid_mask.circom" ] || { echo "Invalid source path: $SRC" >&2; exit 2; }
mkdir -p "$PROJECT"
echo "==> [PATCH] Synchronizing final-validation code into $PROJECT; prior results, artifacts, node_modules, Fabric samples, and venv are preserved"
tar -C "$SRC" --exclude='./results' --exclude='./node_modules' --exclude='./snark_results' --exclude='./artifacts' --exclude='./third_party' --exclude='./.venv' -cf - . | tar -C "$PROJECT" --no-same-owner -xf -
chmod +x "$PROJECT"/scripts/linux/*.sh "$PROJECT"/benchmarks/*.py 2>/dev/null || true
exec bash "$PROJECT/scripts/linux/run_final_validation_suite.sh" "$WINRES"
