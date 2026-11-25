#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; source "$PROJECT/config/config.env"; source "$PROJECT/.venv/bin/activate"
OUT="$PROJECT/results/final_validation/baselines"; SRC="$PROJECT/third_party/TPCH"; mkdir -p "$OUT" "$PROJECT/third_party"
COMMIT='5ec3e8425b187380ec7831908d4037268e7a1b66'
python -m pip install --disable-pip-version-check --no-input pycryptodome ecdsa >/dev/null
if [ ! -d "$SRC/.git" ]; then rm -rf "$SRC"; git clone -q https://github.com/WeiWang-BcLab/TPCH.git "$SRC"; fi
git -C "$SRC" fetch -q origin "$COMMIT"; git -C "$SRC" checkout -q --detach "$COMMIT"
python "$PROJECT/benchmarks/run_tpch_tch_baseline.py" --tch "$SRC/TPCH-Ours and TCH-Ours/TCH.py" --out "$OUT/tpch_tch_core.csv" --reps "${FINAL_TCH_REPS:-20}" --commit "$COMMIT"
