#!/usr/bin/env python3
"""Check the distributed release files and archived research-result consistency."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "RELEASE_MANIFEST.sha256"

def fail(message):
    raise SystemExit("FAIL: " + str(message))

def filehash(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()

def verify_manifest():
    if not MANIFEST.is_file():
        fail("missing RELEASE_MANIFEST.sha256")
    items = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            digest, relative = line.split("  ", 1)
        except ValueError:
            fail("malformed manifest line")
        if relative.startswith("/") or ".." in Path(relative).parts or relative in items:
            fail("invalid or duplicate path in manifest")
        items[relative] = digest
    current_files = {
        p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*")
        if p.is_file() and p != MANIFEST and ".git" not in p.relative_to(ROOT).parts
    }
    if set(items) != current_files:
        missing = sorted(set(items) - current_files)
        extra = sorted(current_files - set(items))
        fail(f"manifest/file listing mismatch: missing={missing[:5]}, extra={extra[:5]}")
    for name, sha in items.items():
        if filehash(ROOT / name) != sha:
            fail(f"SHA-256 mismatch: {name}")
    print(f"PASS: {len(items)} release file hashes match manifest")

def verify_no_sensitive_artifacts():
    forbidden_suffixes = (".wtns", ".zkey", ".ptau", ".pem", ".key", ".p12", ".pfx", ".dd", ".img", ".pcap", ".pcapng")
    forbidden_parts = {"node_modules", ".venv", "third_party", "snark_results", "__pycache__", ".git"}
    for p in ROOT.rglob("*"):
        rel = p.relative_to(ROOT)
        if set(rel.parts) & forbidden_parts:
            fail(f"forbidden path in release: {rel}")
        if p.is_file() and p.suffix.lower() in forbidden_suffixes:
            fail(f"forbidden generated/private file: {rel}")
        if p.is_file() and p.stat().st_size > 25_000_000:
            fail(f"unexpected large file: {rel}")
    print("PASS: no known private-key/witness/disk-image file types or huge files bundled")

def verify_python_syntax():
    count = 0
    for path in ROOT.rglob("*.py"):
        try:
            compile(path.read_bytes(), str(path), "exec")
        except SyntaxError as e:
            fail(f"Python syntax error in {path.relative_to(ROOT)}: {e}")
        count += 1
    print(f"PASS: syntax checked {count} Python files")

def readcsv(rel):
    with (ROOT / rel).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def verify_raw_results():
    prefix = "paper_results/raw/"
    runs = readcsv(prefix + "fabric_batching_runs.csv")
    txs = readcsv(prefix + "fabric_tx_latencies.csv")
    blocks = readcsv(prefix + "fabric_blocks.csv")
    disks = readcsv(prefix + "cfreds_runs.csv")
    exp_conc = {8, 10, 12, 14, 16, 20, 24, 32}
    got = Counter(int(r["concurrency"]) for r in runs)
    if set(got) != exp_conc or any(v != 5 for v in got.values()):
        fail(f" runs per condition mismatch: {got}")
    if len(runs) != 40 or len(txs) != 1600 or len(blocks) != 165:
        fail(f"unexpected  file rows: runs={len(runs)}, tx={len(txs)}, blocks={len(blocks)}")
    if sum(int(r["transactions"]) for r in runs) != 1600:
        fail(" expected transaction totals mismatch")
    if any(int(r["client_failed"]) or int(r["block_invalid"]) or r["tx_audit_consistent"] != "True" for r in runs):
        fail(" recorded failures / client-ledger disagreement")
    if sum(int(b["envelopes"]) for b in blocks) != 1600:
        fail("sum of decoded block envelopes inconsistent")
    cases = Counter(r["case_id"] for r in disks)
    if len(disks) != 15 or cases != {"dfr-01-fat": 5, "dfr-02-ext": 5, "dfr-03-ntfs": 5}:
        fail("unexpected NIST CFReDS record counts")
    provenance = json.loads((ROOT / (prefix + "cfreds_provenance.json")).read_text())
    hashes = {p["case_id"]: p["image_sha256"] for p in provenance}
    for r in disks:
        if r["original_unchanged"].lower() != "true" or r["tamper_detected"].lower() != "true":
            fail(f"CFReDS integrity test result differs for {r['case_id']}")
        if hashes.get(r["case_id"]) != r["image_sha256"]:
            fail(f"CFReDS original SHA256 inconsistent for {r['case_id']}")
    print("PASS: Recorded results contain 40 audited Fabric runs / 1,600 tx / 165 block records")
    print("PASS: Recorded results contain 15 read-only NIST CFReDS runs, three documented cases")

def main():
    verify_manifest()
    verify_no_sensitive_artifacts()
    verify_python_syntax()
    verify_raw_results()
    print("Release checks complete. This is NOT a claim of production cryptographic security.")

if __name__ == "__main__":
    main()
