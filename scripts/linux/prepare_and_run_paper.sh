#!/usr/bin/env bash
set -Eeuo pipefail
SRC="${1:?Windows-mounted bundle path required}"; WINRES="${2:-}"; PROJECT=/root/seal-coc
[ -f "$SRC/circuits/valid_mask.circom" ] || { echo "Invalid source path: $SRC" >&2; exit 2; }
mkdir -p "$PROJECT"
echo "==> [PATCH] Synchronizing paper-experiment code from $SRC into $PROJECT (existing results/artifacts are preserved)"
# Stream ordinary bundle files; never archive WSL root and never use cp -a across DrvFS.
tar -C "$SRC" --exclude='./results' --exclude='./node_modules' --exclude='./snark_results' --exclude='./artifacts' --exclude='./third_party' --exclude='./.venv' -cf - . | tar -C "$PROJECT" --no-same-owner -xf -
chmod +x "$PROJECT"/scripts/linux/*.sh "$PROJECT"/benchmarks/*.py "$PROJECT"/snark_harness/*.py 2>/dev/null || true
exec bash "$PROJECT/scripts/linux/run_paper_suite.sh" "$WINRES"
