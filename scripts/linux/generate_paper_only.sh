#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT=/root/seal-coc; WINRES="${1:-}"
[ -x "$PROJECT/.venv/bin/python" ] || { echo "Missing $PROJECT/.venv" >&2; exit 2; }
source "$PROJECT/.venv/bin/activate"
python -m pip install --disable-pip-version-check --no-input pandas matplotlib tabulate jinja2 >/dev/null
python "$PROJECT/benchmarks/aggregate_results.py" || true
python "$PROJECT/benchmarks/generate_paper_ready.py"
if [ -n "$WINRES" ]; then mkdir -p "$WINRES"; cp -R "$PROJECT/results/." "$WINRES/"; fi
