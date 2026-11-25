# SEAL-CoC

**Predicate-Bound Zero-Knowledge Redaction for Auditable Digital Evidence**

SEAL-CoC is a research prototype combining fixed-size Circom/Groth16 redaction proofs, certificate-bound authorization in Hyperledger Fabric, and forensic integrity benchmarks. This repository contains source code, experiment scripts, measured results, and publication figures.

## Contents

| Path | Purpose |
| --- | --- |
| `circuits/`, `snark_harness/` | Mask-only arithmetic circuits and proof benchmarks |
| `chaincode/`, `fabric/` | Fabric chaincode and test fixtures |
| `benchmarks/`, `evm/` | Security, performance, data-processing and gas benchmarks |
| `scripts/`, `config/` | Reproducible environment setup and experiment orchestration |
| `paper_results/tables/` | Publication tables in CSV format |
| `paper_results/figures/` | Publication figures in PDF format |
| `paper_results/raw/` | Supporting transaction, block and CFReDS observation data |
| `tools/` | Integrity checks and result reaggregation |

## Check archived results

Python 3.9 or later:

```bash
python3 tools/verify_release.py
python3 tools/summarize_results.py
```

The first command verifies checksums, source syntax and recorded-data consistency. The second summarizes Fabric concurrency/batching and NIST CFReDS integrity observations. Neither requires running a Fabric network.

## Run experiments

Use a dedicated Windows research machine with Administrator privileges, WSL2/Ubuntu, Docker and adequate memory/storage. **Inspect the setup scripts before running**: they may install operating-system packages or change local environment settings.

Run the launchers in this order:

1. `RUN_ALL.cmd` — set up the foundational environment and benchmarks.
2. `RUN_PAPER_EXPERIMENTS.cmd` — run the paper experiment suite.
3. `RUN_FINAL_VALIDATION.cmd` — perform repeated final validation.

On Linux, the scripts expect the source tree at `/root/seal-coc` after environment setup. These scripts are laboratory automation, not production deployment procedures.

## Experimental scope

- The zero-knowledge circuit checks a fixed-size byte-level mask transformation with a maximum masking ratio; it does not classify PII or interpret images.
- Hyperledger Fabric implements certificate-bound approvals from three distinct institutional roles out of four. Threshold chameleon-hash operations are benchmarked **separately** and are not claimed as integrated into the Fabric transaction path.
- The archived Fabric batching observations contain 40 test runs, 1,600 reconciled transactions and 165 decoded blocks. The orderer's batch-cut parameters were not independently recovered, so the observed throughput transition does not prove a unique causal mechanism.
- NIST CFReDS forensic reference images are used for integrity and non-destructive overlay experiments, **not** a fully proof-bound filesystem-aware redaction workflow. Recorded source hashes are local fingerprints, not signatures from NIST.

The code in this repository includes experiment runners for the integrated prototype. The separately collected Fabric-batching and disk-image measurement data can be reaggregated from the archived files; **the original collection scripts for these two experiment groups are not bundled**, so the entire measurement campaign cannot be rerun from this repository alone.

## Data and external code

Datasets and third-party repositories are downloaded separately and must be used under their own license and data-use conditions:

- NIST CFReDS: https://cfreds-archive.nist.gov/
- Loghub: https://github.com/logpai/loghub
- CIC-IDS2017: https://www.unb.ca/cic/datasets/ids-2017.html
- TPCH: https://github.com/WeiWang-BcLab/TPCH
- Fabric samples: https://github.com/hyperledger/fabric-samples

No forensic disk images, original case material, private cryptographic keys, SNARK witnesses/proving keys or downloaded third-party repositories are included.

## GitHub publication

Create a blank repository and execute from the extracted directory:

```bash
git init
git add .
git commit -m "Publish SEAL-CoC research artifact"
git branch -M main
git remote add origin https://github.com/USERNAME/SEAL-CoC.git
git push -u origin main
```

Select an appropriate software `LICENSE` after checking contributor and institutional permissions. The repository is a research demonstrator, not a hardened deployment. Cite a specific commit or release tag in the manuscript; a DOI archive can provide additional permanence.
