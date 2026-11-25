#!/usr/bin/env python3
"""Reaggregate provided  measured CSV files. Not an original experiment runner."""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, stdev
from math import sqrt

BASE = Path(__file__).resolve().parents[1]
RAW = BASE / "paper_results" / "raw"

def read_csv(name: str):
    with (RAW / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))

def ci95_t5(xs):
    """Student-t 95% CI half-width for 5 independent repetitions."""
    if len(xs) < 2:
        return float("nan")
    return 2.7764451051977987 * stdev(xs) / sqrt(len(xs)) if len(xs) == 5 else float("nan")

def main():
    runs = read_csv("fabric_batching_runs.csv")
    txs = read_csv("fabric_tx_latencies.csv")
    blocks = read_csv("fabric_blocks.csv")
    disks = read_csv("cfreds_runs.csv")
    by_conc = defaultdict(list)
    for row in runs:
        by_conc[int(row["concurrency"])].append(row)
    print("CLIENT-LEDGER BATCHING CSV REAGGREGATION")
    print(f"Recorded runs: {len(runs)}, tx latency rows: {len(txs)}, decoded blocks: {len(blocks)}")
    print("Concurrency | Runs | Transactions | Mean tx/s | 95% CI +/- | Mean tx/block | Client failures")
    for c in sorted(by_conc):
        records = by_conc[c]
        vals = [float(r["throughput_tx_s"]) for r in records]
        tx_count = sum(int(r["transactions"]) for r in records)
        failed = sum(int(r["client_failed"]) for r in records)
        occupancy = mean(float(r["mean_tx_per_block"]) for r in records)
        print(f"{c:>11} | {len(records):>4} | {tx_count:>12} | {mean(vals):>9.3f} | {ci95_t5(vals):>11.3f} | {occupancy:>13.3f} | {failed:>15}")

    print("\nObserved blocks: distributions (envelopes/block -> count)")
    for c in sorted(by_conc):
        distribution = Counter(int(r["envelopes"]) for r in blocks if int(r["concurrency"]) == c)
        print(c, dict(sorted(distribution.items())))

    by_disk = defaultdict(list)
    for row in disks:
        by_disk[row["case_id"]].append(row)
    print("\nNIST CFReDS DFR integrity-only CSV REAGGREGATION")
    print("Case | Runs | Image MiB | Ingest mean MiB/s | Full verify mean ms | Original unchanged | Tamper detected")
    for case, records in sorted(by_disk.items()):
        ingest = mean(float(r["acquire_throughput_mib_s"]) for r in records)
        verify = mean(float(r["full_verify_ms"]) for r in records)
        size = int(records[0]["image_bytes"]) / (1024 * 1024)
        orig = all(r["original_unchanged"].lower() == "true" for r in records)
        tamper = all(r["tamper_detected"].lower() == "true" for r in records)
        print(f"{case:12} | {len(records):>4} | {size:>9.3f} | {ingest:>17.3f} | {verify:>19.2f} | {str(orig):>18} | {tamper}")
    print("\nLIMITATION: The original measurement-collection scripts are not included in this repository.")
    print("LIMITATION: Fabric BatchTimeout/MaxMessageCount could not be decoded from the archived results.")

if __name__ == "__main__":
    main()
