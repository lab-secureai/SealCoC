#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$PROJECT/config/config.env"
OUT="$PROJECT/results/environment.txt"
{
 echo "timestamp_utc=$(date -u +%FT%TZ)"
 echo "kernel=$(uname -a)"
 echo "cpu=$(lscpu | grep 'Model name' | head -1 | cut -d: -f2- | xargs)"
 echo "cpus=$(nproc)"
 echo "memory=$(free -h | awk '/Mem:/{print $2}')"
 echo "fabric_requested=$FABRIC_VERSION"
 echo "fabric_ca_requested=$FABRIC_CA_VERSION"
 peer version 2>/dev/null || true
 fabric-ca-client version 2>/dev/null || true
 docker --version
 docker compose version
 circom --version
 node --version
 npm --version
 python3 --version
 go version
 echo "snarkjs=$($PROJECT/node_modules/.bin/snarkjs --version 2>/dev/null || true)"
 echo "go_modules:"; (cd "$PROJECT/chaincode/sealcoc" && go list -m all) || true
 echo "docker_images:"; docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' | grep -E 'hyperledger|couchdb' || true
} > "$OUT"
