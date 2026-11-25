#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$PROJECT/config/config.env"
source "$PROJECT/.venv/bin/activate"
OUT="$PROJECT/results/final_validation/fabric"; mkdir -p "$OUT"
FABRIC_HOME="$PROJECT/third_party/fabric-samples"; NETWORK="$FABRIC_HOME/test-network"
export PATH="$FABRIC_HOME/bin:$PATH"; export FABRIC_CFG_PATH="$FABRIC_HOME/config"
MONO="$PROJECT/bin/monotime"; mkdir -p "$PROJECT/bin"
[ -x "$MONO" ] || gcc -O2 "$PROJECT/benchmarks/monotime.c" -o "$MONO"
now_ns(){ "$MONO"; }
msdiff(){ awk -v d="$1" 'BEGIN{printf "%.3f",d/1000000}'; }
SIZES="${SNARK_SIZES//,/ }"
VERIFY_REPS="${FINAL_VERIFY_REPS:-30}"; VERIFY_WARMUP="${FINAL_VERIFY_WARMUP:-5}"
SUBMIT_REPS="${FINAL_SUBMIT_REPS:-15}"; SUBMIT_WARMUP="${FINAL_SUBMIT_WARMUP:-2}"
FLOW_REPS="${FINAL_FLOW_REPS:-20}"; FLOW_WARMUP="${FINAL_FLOW_WARMUP:-3}"
TXN="${FINAL_THROUGHPUT_TX:-40}"; THR_RUNS="${FINAL_THROUGHPUT_RUNS:-5}"; CONCURRENCIES="${FINAL_CONCURRENCIES:-1 2 4 8 16}"
WAN_REPS="${FINAL_WAN_REPS:-10}"; WAN_WARMUP="${FINAL_WAN_WARMUP:-1}"; E2E_REPS="${FINAL_E2E_REPS:-10}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"

echo "final Fabric validation run: $RUN_ID" | tee "$OUT/run_id.txt"
cd "$NETWORK"
./network.sh down || true
./network.sh up createChannel -ca -c "$FABRIC_CHANNEL"
(cd "$PROJECT/chaincode/sealcoc" && go mod tidy && go mod vendor)
./network.sh deployCC -c "$FABRIC_CHANNEL" -ccn "$FABRIC_CC_NAME" -ccp "$PROJECT/chaincode/sealcoc" -ccl go -ccv "$FABRIC_CC_VERSION" -ccs "$FABRIC_CC_SEQUENCE"

ORDERER_CA="$NETWORK/organizations/ordererOrganizations/example.com/orderers/orderer.example.com/msp/tlscacerts/tlsca.example.com-cert.pem"
ORG1_CA="$NETWORK/organizations/peerOrganizations/org1.example.com/peers/peer0.org1.example.com/tls/ca.crt"
ORG2_CA="$NETWORK/organizations/peerOrganizations/org2.example.com/peers/peer0.org2.example.com/tls/ca.crt"
register_user(){
  local org="$1" name="$2" secret="$3" role="$4" port="$5" caname="$6" attrs="${7:-}"
  local orgdir="$NETWORK/organizations/peerOrganizations/org${org}.example.com"; local ca="$NETWORK/organizations/fabric-ca/org${org}/ca-cert.pem"
  export FABRIC_CA_CLIENT_HOME="$orgdir"; local attrarg=(); [ -n "$attrs" ] && attrarg=(--id.attrs "$attrs")
  fabric-ca-client register --caname "$caname" --id.name "$name" --id.secret "$secret" --id.type client "${attrarg[@]}" --tls.certfiles "$ca" >/dev/null 2>&1 || true
  local userdir="$orgdir/users/${name}@org${org}.example.com/msp"; rm -rf "$userdir"
  fabric-ca-client enroll -u "https://${name}:${secret}@localhost:${port}" --caname "$caname" -M "$userdir" --tls.certfiles "$ca" >/dev/null
  cp "$orgdir/msp/config.yaml" "$userdir/config.yaml"
}
register_user 1 investigator investigatorpw I 7054 ca-org1 'seal.role=I:ecert'
register_user 1 prosecutor prosecutorpw P 7054 ca-org1 'seal.role=P:ecert'
register_user 2 court courtpw C 8054 ca-org2 'seal.role=C:ecert'
register_user 2 defense defensepw D 8054 ca-org2 'seal.role=D:ecert'
set_identity(){
  case "$1" in
    I) export CORE_PEER_LOCALMSPID=Org1MSP CORE_PEER_MSPCONFIGPATH="$NETWORK/organizations/peerOrganizations/org1.example.com/users/investigator@org1.example.com/msp" CORE_PEER_ADDRESS=localhost:7051 CORE_PEER_TLS_ROOTCERT_FILE="$ORG1_CA" ;;
    P) export CORE_PEER_LOCALMSPID=Org1MSP CORE_PEER_MSPCONFIGPATH="$NETWORK/organizations/peerOrganizations/org1.example.com/users/prosecutor@org1.example.com/msp" CORE_PEER_ADDRESS=localhost:7051 CORE_PEER_TLS_ROOTCERT_FILE="$ORG1_CA" ;;
    C) export CORE_PEER_LOCALMSPID=Org2MSP CORE_PEER_MSPCONFIGPATH="$NETWORK/organizations/peerOrganizations/org2.example.com/users/court@org2.example.com/msp" CORE_PEER_ADDRESS=localhost:9051 CORE_PEER_TLS_ROOTCERT_FILE="$ORG2_CA" ;;
    D) export CORE_PEER_LOCALMSPID=Org2MSP CORE_PEER_MSPCONFIGPATH="$NETWORK/organizations/peerOrganizations/org2.example.com/users/defense@org2.example.com/msp" CORE_PEER_ADDRESS=localhost:9051 CORE_PEER_TLS_ROOTCERT_FILE="$ORG2_CA" ;;
  esac
  export CORE_PEER_TLS_ENABLED=true
}
invoke(){
  peer chaincode invoke -o localhost:7050 --ordererTLSHostnameOverride orderer.example.com --tls --cafile "$ORDERER_CA" -C "$FABRIC_CHANNEL" -n "$FABRIC_CC_NAME" \
    --peerAddresses localhost:7051 --tlsRootCertFiles "$ORG1_CA" --peerAddresses localhost:9051 --tlsRootCertFiles "$ORG2_CA" -c "$1" --waitForEvent >/dev/null
}
query(){ peer chaincode query -C "$FABRIC_CHANNEL" -n "$FABRIC_CC_NAME" -c "$1"; }
set_identity I
for N in $SIZES; do
  D="$PROJECT/snark_results/n$N"; [ -f "$D/proof_0.json" ] || { echo "missing SNARK artifact n$N" >&2; exit 10; }
  python "$PROJECT/fabric/prepare_fixture.py" --dir "$D" --out "$OUT/fixture_${N}.json" >/dev/null
  VK="$(jq -c . "$D/verification_key.json")"
  invoke "$(jq -cn --arg a SetVerifierKey --arg id "mask-$N" --arg vk "$VK" '{Args:[$a,$id,$vk]}')"
done
fixture_var(){ jq -r ".$2" "$OUT/fixture_$1.json"; }
proof_var(){ jq -c . "$PROJECT/snark_results/n$1/proof_0.json"; }
public_var(){ jq -c . "$PROJECT/snark_results/n$1/public_0.json"; }
register_ev(){
  local id="$1" N="$2" sha op ctx mr meta
  sha=$(fixture_var "$N" original_sha256); op=$(fixture_var "$N" original_poseidon); ctx=$(fixture_var "$N" context); mr=$(fixture_var "$N" merkle_root); meta=$(jq -c .metadata "$OUT/fixture_${N}.json")
  invoke "$(jq -cn --arg a RegisterEvidence --arg id "$id" --arg sha "$sha" --arg op "$op" --arg ctx "$ctx" --arg mr "$mr" --arg meta "$meta" '{Args:[$a,$id,$sha,$op,$ctx,$mr,$meta]}')"
}
submit_payload(){
  local rid="$1" eid="$2" N="$3" red proof pub
  red=$(fixture_var "$N" redacted_poseidon); proof=$(proof_var "$N"); pub=$(public_var "$N")
  jq -cn --arg a SubmitRedaction --arg rid "$rid" --arg eid "$eid" --arg cid "mask-$N" --arg rc "$red" --arg pol MASK-50-v1 --arg pr "$proof" --arg pu "$pub" '{Args:[$a,$rid,$eid,$cid,$rc,$pol,$pr,$pu]}'
}
full_workflow(){
  local rid="$1" eid="$2" N="$3"
  set_identity I; invoke "$(submit_payload "$rid" "$eid" "$N")"
  for role in I P C; do set_identity "$role"; invoke "$(jq -cn --arg a ApproveRedaction --arg rid "$rid" '{Args:[$a,$rid]}')"; done
  set_identity D; invoke "$(jq -cn --arg a CommitRedaction --arg rid "$rid" '{Args:[$a,$rid]}')"
}

# verifier latency by circuit size, with warm-up and CLOCK_MONOTONIC_RAW timing.
echo 'size_B,rep,latency_ms,status,timer' > "$OUT/verify_by_size.csv"
for N in $SIZES; do
  proof=$(proof_var "$N"); pub=$(public_var "$N"); p=$(jq -cn --arg a VerifyOnly --arg cid "mask-$N" --arg pr "$proof" --arg pu "$pub" '{Args:[$a,$cid,$pr,$pu]}')
  for ((r=1;r<=VERIFY_WARMUP;r++)); do query "$p" >/dev/null; done
  for ((r=1;r<=VERIFY_REPS;r++)); do t0=$(now_ns); query "$p" >/dev/null; t1=$(now_ns); d=$((t1-t0)); [ "$d" -gt 0 ] || { echo "nonpositive monotonic duration" >&2; exit 31; }; echo "$N,$r,$(msdiff "$d"),MEASURED,CLOCK_MONOTONIC_RAW" >> "$OUT/verify_by_size.csv"; done
done

# ordered SubmitRedaction latency by size.
echo 'size_B,rep,latency_ms,status,timer' > "$OUT/submit_by_size.csv"
for N in $SIZES; do
  eid="submit-e-$N"; set_identity I; register_ev "$eid" "$N"
  for ((r=1;r<=SUBMIT_WARMUP;r++)); do invoke "$(submit_payload "submit-w-$N-$r" "$eid" "$N")"; done
  for ((r=1;r<=SUBMIT_REPS;r++)); do rid="submit-r-$N-$r"; p=$(submit_payload "$rid" "$eid" "$N"); t0=$(now_ns); invoke "$p"; t1=$(now_ns); echo "$N,$r,$(msdiff $((t1-t0))),MEASURED,CLOCK_MONOTONIC_RAW" >> "$OUT/submit_by_size.csv"; done
done

# throughput, five independent runs per concurrency.
echo 'concurrency,run,transactions,successful,failed,elapsed_ms,throughput_tx_s,status' > "$OUT/throughput_runs.csv"
N=${FABRIC_CIRCUIT_SIZE}
for C in $CONCURRENCIES; do
  for ((run=1;run<=THR_RUNS;run++)); do
    for ((i=1;i<=TXN;i++)); do set_identity I; register_ev "throughput-e-$C-$run-$i" "$N"; done
    fail="$OUT/throughput_fail_${C}_${run}.txt"; : > "$fail"; start=$(now_ns)
    for ((i=1;i<=TXN;i++)); do
      ( set_identity I; p=$(submit_payload "throughput-r-$C-$run-$i" "throughput-e-$C-$run-$i" "$N"); invoke "$p" || echo "$i" >> "$fail" ) &
      while [ "$(jobs -pr | wc -l)" -ge "$C" ]; do sleep 0.02; done
    done
    wait; end=$(now_ns); f=$(wc -l < "$fail"); ok=$((TXN-f)); elapsed=$((end-start)); thr=$(awk -v n="$ok" -v d="$elapsed" 'BEGIN{printf "%.4f",n/(d/1e9)}')
    echo "$C,$run,$TXN,$ok,$f,$(msdiff "$elapsed"),$thr,MEASURED" >> "$OUT/throughput_runs.csv"
  done
done

# workflow breakdown, warmed and repeated.
for ((w=1;w<=FLOW_WARMUP;w++)); do set_identity I; register_ev "v4-w-e-$w" "$N"; full_workflow "v4-w-r-$w" "v4-w-e-$w" "$N"; done
echo 'rep,submit_ms,approve_I_ms,approve_P_ms,approve_C_ms,commit_ms,end_to_end_ms,status,timer' > "$OUT/authorization_workflow.csv"
for ((r=1;r<=FLOW_REPS;r++)); do
  eid="workflow-e-$r"; rid="workflow-r-$r"; set_identity I; register_ev "$eid" "$N"; total0=$(now_ns)
  t0=$(now_ns); invoke "$(submit_payload "$rid" "$eid" "$N")"; t1=$(now_ns); sm=$(msdiff $((t1-t0)))
  vals=(); for role in I P C; do set_identity "$role"; t0=$(now_ns); invoke "$(jq -cn --arg a ApproveRedaction --arg rid "$rid" '{Args:[$a,$rid]}')"; t1=$(now_ns); vals+=("$(msdiff $((t1-t0)))"); done
  set_identity D; t0=$(now_ns); invoke "$(jq -cn --arg a CommitRedaction --arg rid "$rid" '{Args:[$a,$rid]}')"; t1=$(now_ns); cm=$(msdiff $((t1-t0))); total1=$(now_ns)
  echo "$r,$sm,${vals[0]},${vals[1]},${vals[2]},$cm,$(msdiff $((total1-total0))),MEASURED,CLOCK_MONOTONIC_RAW" >> "$OUT/authorization_workflow.csv"
done

# WAN sensitivity; verify actual RTT between peer namespaces using host ping under nsenter.
netem_clear(){ for c in peer0.org1.example.com peer0.org2.example.com orderer.example.com; do pid=$(docker inspect -f '{{.State.Pid}}' "$c" 2>/dev/null || true); [ -n "$pid" ] && nsenter -t "$pid" -n tc qdisc del dev eth0 root 2>/dev/null || true; done; }
netem_set(){ local d="$1"; netem_clear; [ "$d" = 0 ] && return 0; for c in peer0.org1.example.com peer0.org2.example.com orderer.example.com; do pid=$(docker inspect -f '{{.State.Pid}}' "$c"); nsenter -t "$pid" -n tc qdisc replace dev eth0 root netem delay "${d}ms"; done; }
measure_rtt(){
  local p1 p2 ip2 out
  p1=$(docker inspect -f '{{.State.Pid}}' peer0.org1.example.com); ip2=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' peer0.org2.example.com)
  out=$(nsenter -t "$p1" -n ping -c 5 -W 2 "$ip2" 2>/dev/null || true)
  echo "$out" | awk -F'=' '/^rtt|^round-trip/{gsub(/ /,"",$2); split($2,a,"/"); print a[2]}'
}
trap 'netem_clear || true' EXIT
echo 'target_rtt_ms,injected_one_way_ms,measured_rtt_ms,rep,end_to_end_ms,status' > "$OUT/wan_netem.csv"
for rtt in 0 20 50 100; do
  d=$((rtt/2)); if ! netem_set "$d"; then echo "$rtt,$d,,, ,SKIPPED_NETEM_UNAVAILABLE" >> "$OUT/wan_netem.csv"; continue; fi
  sleep 1; actual=$(measure_rtt); [ -n "$actual" ] || actual=""
  for ((w=1;w<=WAN_WARMUP;w++)); do set_identity I; register_ev "v5-w-e-$rtt-$w" "$N"; full_workflow "v5-w-r-$rtt-$w" "v5-w-e-$rtt-$w" "$N"; done
  for ((r=1;r<=WAN_REPS;r++)); do set_identity I; eid="wan-e-$rtt-$r"; rid="wan-r-$rtt-$r"; register_ev "$eid" "$N"; t0=$(now_ns); full_workflow "$rid" "$eid" "$N"; t1=$(now_ns); echo "$rtt,$d,$actual,$r,$(msdiff $((t1-t0))),MEASURED_NETEM" >> "$OUT/wan_netem.csv"; done
  netem_clear
done

# : true E2E incl. fresh witness/proof and ledger commit, n>=10 per size.
echo 'size_B,rep,witness_ms,prove_ms,submit_ms,approvals_ms,commit_ms,end_to_end_ms,status,timer' > "$OUT/true_end_to_end.csv"
SNARKJS="$PROJECT/node_modules/.bin/snarkjs"
for EN in 1024 4096; do
  ED="$PROJECT/snark_results/n$EN"; JS="$ED/mask_${EN}_js"; WASM="$JS/mask_${EN}.wasm"; ZKEY="$ED/circuit_final.zkey"; [ -s "$ZKEY" ] || continue
  # one unrecorded proof warm-up per size
  node "$JS/generate_witness.js" "$WASM" "$ED/input.json" "$OUT/e2e_warm_${EN}.wtns" >/dev/null
  "$SNARKJS" groth16 prove "$ZKEY" "$OUT/e2e_warm_${EN}.wtns" "$OUT/e2e_warm_${EN}_proof.json" "$OUT/e2e_warm_${EN}_public.json" >/dev/null
  rm -f "$OUT/e2e_warm_${EN}.wtns" "$OUT/e2e_warm_${EN}_proof.json" "$OUT/e2e_warm_${EN}_public.json"
  for ((r=1;r<=E2E_REPS;r++)); do
    eid="-e-$EN-$r"; rid="-r-$EN-$r"; set_identity I; register_ev "$eid" "$EN"; w="$OUT/e2e_${EN}_${r}.wtns"; pr="$OUT/e2e_${EN}_${r}_proof.json"; pu="$OUT/e2e_${EN}_${r}_public.json"
    total0=$(now_ns); t0=$(now_ns); node "$JS/generate_witness.js" "$WASM" "$ED/input.json" "$w" >/dev/null; t1=$(now_ns); wm=$(msdiff $((t1-t0)))
    t0=$(now_ns); "$SNARKJS" groth16 prove "$ZKEY" "$w" "$pr" "$pu" >/dev/null; t1=$(now_ns); pm=$(msdiff $((t1-t0)))
    pproof=$(jq -c . "$pr"); ppub=$(jq -c . "$pu"); pred=$(jq -r '.[1]' "$pu"); payload=$(jq -cn --arg a SubmitRedaction --arg rid "$rid" --arg eid "$eid" --arg cid "mask-$EN" --arg rc "$pred" --arg pol MASK-50-v1 --arg pr "$pproof" --arg pu "$ppub" '{Args:[$a,$rid,$eid,$cid,$rc,$pol,$pr,$pu]}')
    t0=$(now_ns); invoke "$payload"; t1=$(now_ns); sm=$(msdiff $((t1-t0)))
    app0=$(now_ns); for role in I P C; do set_identity "$role"; invoke "$(jq -cn --arg a ApproveRedaction --arg rid "$rid" '{Args:[$a,$rid]}')"; done; app1=$(now_ns); am=$(msdiff $((app1-app0)))
    set_identity D; t0=$(now_ns); invoke "$(jq -cn --arg a CommitRedaction --arg rid "$rid" '{Args:[$a,$rid]}')"; t1=$(now_ns); cm=$(msdiff $((t1-t0))); total1=$(now_ns)
    echo "$EN,$r,$wm,$pm,$sm,$am,$cm,$(msdiff $((total1-total0))),MEASURED_TRUE_E2E,CLOCK_MONOTONIC_RAW" >> "$OUT/true_end_to_end.csv"
    if [ "$r" -gt 1 ]; then rm -f "$w" "$pr" "$pu"; fi
  done
done

netem_clear || true
docker ps --format '{{.Names}},{{.Image}},{{.Status}}' > "$OUT/docker_state.csv"
peer channel getinfo -c "$FABRIC_CHANNEL" > "$OUT/channel_info.txt"
if [ "${KEEP_FABRIC_UP:-0}" != 1 ]; then ./network.sh down; fi
