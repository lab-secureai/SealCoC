#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$PROJECT/config/config.env"
source "$PROJECT/.venv/bin/activate"
FABRIC_HOME="$PROJECT/third_party/fabric-samples"; NETWORK="$FABRIC_HOME/test-network"; OUT="$PROJECT/results/fabric_paper"
mkdir -p "$OUT"; export PATH="$FABRIC_HOME/bin:$PATH"; export FABRIC_CFG_PATH="$FABRIC_HOME/config"
VERIFY_REPS="${FABRIC_PAPER_VERIFY_REPS:-20}"; SUBMIT_REPS="${FABRIC_PAPER_SUBMIT_REPS:-10}"; FLOW_REPS="${FABRIC_PAPER_FLOW_REPS:-10}"; TXN="${FABRIC_PAPER_THROUGHPUT_TX:-32}"
CONCURRENCIES="${FABRIC_PAPER_CONCURRENCIES:-1 2 4 8 16}"; SIZES="${SNARK_SIZES//,/ }"

cd "$NETWORK"; ./network.sh down || true; ./network.sh up createChannel -ca -c "$FABRIC_CHANNEL"
(cd "$PROJECT/chaincode/sealcoc" && go mod tidy && go mod vendor)
./network.sh deployCC -c "$FABRIC_CHANNEL" -ccn "$FABRIC_CC_NAME" -ccp "$PROJECT/chaincode/sealcoc" -ccl go -ccv "$FABRIC_CC_VERSION" -ccs "$FABRIC_CC_SEQUENCE"

ORDERER_CA="$NETWORK/organizations/ordererOrganizations/example.com/orderers/orderer.example.com/msp/tlscacerts/tlsca.example.com-cert.pem"
ORG1_CA="$NETWORK/organizations/peerOrganizations/org1.example.com/peers/peer0.org1.example.com/tls/ca.crt"
ORG2_CA="$NETWORK/organizations/peerOrganizations/org2.example.com/peers/peer0.org2.example.com/tls/ca.crt"

register_user(){
  local org="$1" name="$2" secret="$3" role="$4" port="$5" caname="$6" attrs="${7:-}"
  local orgdir="$NETWORK/organizations/peerOrganizations/org${org}.example.com"; local ca="$NETWORK/organizations/fabric-ca/org${org}/ca-cert.pem"
  export FABRIC_CA_CLIENT_HOME="$orgdir"
  local attrarg=(); [ -n "$attrs" ] && attrarg=(--id.attrs "$attrs")
  fabric-ca-client register --caname "$caname" --id.name "$name" --id.secret "$secret" --id.type client "${attrarg[@]}" --tls.certfiles "$ca" >/dev/null 2>&1 || true
  local userdir="$orgdir/users/${name}@org${org}.example.com/msp"; rm -rf "$userdir"
  fabric-ca-client enroll -u "https://${name}:${secret}@localhost:${port}" --caname "$caname" -M "$userdir" --tls.certfiles "$ca" >/dev/null
  cp "$orgdir/msp/config.yaml" "$userdir/config.yaml"
}
register_user 1 investigator investigatorpw I 7054 ca-org1 'seal.role=I:ecert'
register_user 1 prosecutor prosecutorpw P 7054 ca-org1 'seal.role=P:ecert'
register_user 2 court courtpw C 8054 ca-org2 'seal.role=C:ecert'
register_user 2 defense defensepw D 8054 ca-org2 'seal.role=D:ecert'
register_user 1 outsider outsiderpw U 7054 ca-org1 ''

set_identity(){
  case "$1" in
    I) export CORE_PEER_LOCALMSPID=Org1MSP CORE_PEER_MSPCONFIGPATH="$NETWORK/organizations/peerOrganizations/org1.example.com/users/investigator@org1.example.com/msp" CORE_PEER_ADDRESS=localhost:7051 CORE_PEER_TLS_ROOTCERT_FILE="$ORG1_CA" ;;
    P) export CORE_PEER_LOCALMSPID=Org1MSP CORE_PEER_MSPCONFIGPATH="$NETWORK/organizations/peerOrganizations/org1.example.com/users/prosecutor@org1.example.com/msp" CORE_PEER_ADDRESS=localhost:7051 CORE_PEER_TLS_ROOTCERT_FILE="$ORG1_CA" ;;
    C) export CORE_PEER_LOCALMSPID=Org2MSP CORE_PEER_MSPCONFIGPATH="$NETWORK/organizations/peerOrganizations/org2.example.com/users/court@org2.example.com/msp" CORE_PEER_ADDRESS=localhost:9051 CORE_PEER_TLS_ROOTCERT_FILE="$ORG2_CA" ;;
    D) export CORE_PEER_LOCALMSPID=Org2MSP CORE_PEER_MSPCONFIGPATH="$NETWORK/organizations/peerOrganizations/org2.example.com/users/defense@org2.example.com/msp" CORE_PEER_ADDRESS=localhost:9051 CORE_PEER_TLS_ROOTCERT_FILE="$ORG2_CA" ;;
    U) export CORE_PEER_LOCALMSPID=Org1MSP CORE_PEER_MSPCONFIGPATH="$NETWORK/organizations/peerOrganizations/org1.example.com/users/outsider@org1.example.com/msp" CORE_PEER_ADDRESS=localhost:7051 CORE_PEER_TLS_ROOTCERT_FILE="$ORG1_CA" ;;
  esac
  export CORE_PEER_TLS_ENABLED=true
}
invoke(){
  peer chaincode invoke -o localhost:7050 --ordererTLSHostnameOverride orderer.example.com --tls --cafile "$ORDERER_CA" -C "$FABRIC_CHANNEL" -n "$FABRIC_CC_NAME" \
    --peerAddresses localhost:7051 --tlsRootCertFiles "$ORG1_CA" --peerAddresses localhost:9051 --tlsRootCertFiles "$ORG2_CA" -c "$1" --waitForEvent >/dev/null
}
invoke_capture(){
  peer chaincode invoke -o localhost:7050 --ordererTLSHostnameOverride orderer.example.com --tls --cafile "$ORDERER_CA" -C "$FABRIC_CHANNEL" -n "$FABRIC_CC_NAME" \
    --peerAddresses localhost:7051 --tlsRootCertFiles "$ORG1_CA" --peerAddresses localhost:9051 --tlsRootCertFiles "$ORG2_CA" -c "$1" --waitForEvent 2>&1
}
query(){ peer chaincode query -C "$FABRIC_CHANNEL" -n "$FABRIC_CC_NAME" -c "$1"; }
msdiff(){ awk -v d="$1" 'BEGIN{printf "%.3f",d/1000000}'; }

# Prepare all fixtures and verifier keys.
set_identity I
for N in $SIZES; do
  D="$PROJECT/snark_results/n$N"; [ -f "$D/proof_0.json" ] || { echo "missing SNARK n$N" >&2; exit 10; }
  python "$PROJECT/fabric/prepare_fixture.py" --dir "$D" --out "$OUT/fixture_${N}.json" >/dev/null
  VK="$(jq -c . "$D/verification_key.json")"
  invoke "$(jq -cn --arg a SetVerifierKey --arg id "mask-$N" --arg vk "$VK" '{Args:[$a,$id,$vk]}')"
done

fixture_var(){ local N="$1" k="$2"; jq -r ".$k" "$OUT/fixture_${N}.json"; }
proof_var(){ jq -c . "$PROJECT/snark_results/n$1/proof_0.json"; }
public_var(){ jq -c . "$PROJECT/snark_results/n$1/public_0.json"; }
register_ev(){
  local id="$1" N="$2"; local sha op ctx mr meta
  sha=$(fixture_var "$N" original_sha256); op=$(fixture_var "$N" original_poseidon); ctx=$(fixture_var "$N" context); mr=$(fixture_var "$N" merkle_root); meta=$(jq -c .metadata "$OUT/fixture_${N}.json" | jq -r .)
  invoke "$(jq -cn --arg a RegisterEvidence --arg id "$id" --arg sha "$sha" --arg op "$op" --arg ctx "$ctx" --arg mr "$mr" --arg meta "$meta" '{Args:[$a,$id,$sha,$op,$ctx,$mr,$meta]}')"
}
submit_payload(){ local rid="$1" eid="$2" N="$3"; local red proof pub; red=$(fixture_var "$N" redacted_poseidon); proof=$(proof_var "$N"); pub=$(public_var "$N"); jq -cn --arg a SubmitRedaction --arg rid "$rid" --arg eid "$eid" --arg cid "mask-$N" --arg rc "$red" --arg pol MASK-50-v1 --arg pr "$proof" --arg pu "$pub" '{Args:[$a,$rid,$eid,$cid,$rc,$pol,$pr,$pu]}'; }

# F1: verifier latency by circuit size.
echo 'size_B,rep,latency_ms,status' > "$OUT/f1_verify_by_size.csv"
for N in $SIZES; do
  proof=$(proof_var "$N"); pub=$(public_var "$N"); p="$(jq -cn --arg a VerifyOnly --arg cid "mask-$N" --arg pr "$proof" --arg pu "$pub" '{Args:[$a,$cid,$pr,$pu]}')"
  for ((r=1;r<=VERIFY_REPS;r++)); do t0=$(date +%s%N); query "$p" >/dev/null; t1=$(date +%s%N); echo "$N,$r,$(msdiff $((t1-t0))),MEASURED" >> "$OUT/f1_verify_by_size.csv"; done
done

# F2: ordered submission latency by circuit size.
echo 'size_B,rep,latency_ms,status' > "$OUT/f2_submit_by_size.csv"
for N in $SIZES; do
  eid="f2-e-$N"; register_ev "$eid" "$N"
  for ((r=1;r<=SUBMIT_REPS;r++)); do rid="f2-r-$N-$r"; p=$(submit_payload "$rid" "$eid" "$N"); t0=$(date +%s%N); invoke "$p"; t1=$(date +%s%N); echo "$N,$r,$(msdiff $((t1-t0))),MEASURED" >> "$OUT/f2_submit_by_size.csv"; done
done

# F8: emulated WAN sensitivity for the complete pre-proved 3-of-4 workflow.
# target_rtt_ms is an experimental label; we inject half that delay on peer/orderer eth0 interfaces.
netem_clear(){
  for c in peer0.org1.example.com peer0.org2.example.com orderer.example.com; do
    pid=$(docker inspect -f '{{.State.Pid}}' "$c" 2>/dev/null || true); [ -n "$pid" ] && nsenter -t "$pid" -n tc qdisc del dev eth0 root 2>/dev/null || true
  done
}
netem_set(){
  local d="$1"; netem_clear
  [ "$d" = 0 ] && return 0
  for c in peer0.org1.example.com peer0.org2.example.com orderer.example.com; do
    pid=$(docker inspect -f '{{.State.Pid}}' "$c"); nsenter -t "$pid" -n tc qdisc replace dev eth0 root netem delay "${d}ms"
  done
}
trap 'netem_clear || true' EXIT
WAN_REPS="${FABRIC_PAPER_WAN_REPS:-3}"
for rtt in 0 20 50 100; do for ((r=1;r<=WAN_REPS;r++)); do set_identity I; register_ev "f8-e-$rtt-$r" "$FABRIC_CIRCUIT_SIZE"; done; done
echo 'target_rtt_ms,injected_one_way_ms,rep,end_to_end_ms,status' > "$OUT/f8_wan_netem.csv"
for rtt in 0 20 50 100; do
  d=$((rtt/2))
  if ! netem_set "$d"; then
    netem_clear || true
    echo "$rtt,$d,,,SKIPPED_NETEM_UNAVAILABLE" >> "$OUT/f8_wan_netem.csv"
    echo "WARNING: tc/netem unavailable for target RTT $rtt ms; continuing without failing the paper suite." >&2
    continue
  fi
  for ((r=1;r<=WAN_REPS;r++)); do
    eid="f8-e-$rtt-$r"; rid="f8-r-$rtt-$r"; set_identity I; total0=$(date +%s%N); invoke "$(submit_payload "$rid" "$eid" "$FABRIC_CIRCUIT_SIZE")"
    for role in I P C; do set_identity "$role"; invoke "$(jq -cn --arg a ApproveRedaction --arg rid "$rid" '{Args:[$a,$rid]}')"; done
    set_identity D; invoke "$(jq -cn --arg a CommitRedaction --arg rid "$rid" '{Args:[$a,$rid]}')"; total1=$(date +%s%N)
    echo "$rtt,$d,$r,$(msdiff $((total1-total0))),MEASURED_NETEM" >> "$OUT/f8_wan_netem.csv"
  done
  netem_clear
done

# F3: throughput vs concurrency using independent evidence keys.
echo 'concurrency,transactions,successful,failed,elapsed_ms,throughput_tx_s,status' > "$OUT/f3_throughput_scaling.csv"
N=${FABRIC_CIRCUIT_SIZE};
for C in $CONCURRENCIES; do
  for ((i=1;i<=TXN;i++)); do register_ev "f3-e-$C-$i" "$N"; done
  fail="$OUT/f3_fail_${C}.txt"; : > "$fail"; start=$(date +%s%N)
  for ((i=1;i<=TXN;i++)); do
    ( p=$(submit_payload "f3-r-$C-$i" "f3-e-$C-$i" "$N"); invoke "$p" || echo "$i" >> "$fail" ) &
    while [ "$(jobs -pr | wc -l)" -ge "$C" ]; do sleep 0.03; done
  done
  wait; end=$(date +%s%N); f=$(wc -l < "$fail"); ok=$((TXN-f)); elapsed=$((end-start)); thr=$(awk -v n="$ok" -v d="$elapsed" 'BEGIN{printf "%.3f",n/(d/1e9)}')
  echo "$C,$TXN,$ok,$f,$(msdiff "$elapsed"),$thr,MEASURED" >> "$OUT/f3_throughput_scaling.csv"
done

# F4: full 3-of-4 workflow phase latency.
echo 'rep,submit_ms,approve_I_ms,approve_P_ms,approve_C_ms,commit_ms,end_to_end_ms,status' > "$OUT/f4_workflow.csv"
for ((r=1;r<=FLOW_REPS;r++)); do
  eid="f4-e-$r"; rid="f4-r-$r"; set_identity I; register_ev "$eid" "$N"; p=$(submit_payload "$rid" "$eid" "$N"); total0=$(date +%s%N)
  t0=$(date +%s%N); invoke "$p"; t1=$(date +%s%N); sm=$(msdiff $((t1-t0)))
  vals=()
  for role in I P C; do set_identity "$role"; t0=$(date +%s%N); invoke "$(jq -cn --arg a ApproveRedaction --arg rid "$rid" '{Args:[$a,$rid]}')"; t1=$(date +%s%N); vals+=("$(msdiff $((t1-t0)))"); done
  set_identity D; t0=$(date +%s%N); invoke "$(jq -cn --arg a CommitRedaction --arg rid "$rid" '{Args:[$a,$rid]}')"; t1=$(date +%s%N); cm=$(msdiff $((t1-t0))); total1=$(date +%s%N)
  echo "$r,$sm,${vals[0]},${vals[1]},${vals[2]},$cm,$(msdiff $((total1-total0))),MEASURED" >> "$OUT/f4_workflow.csv"
done

# F5: measured ledger storage growth. Pre-register 50 evidence objects, then store requests cumulatively.
set_identity I
for ((i=1;i<=50;i++)); do register_ev "f5-e-$i" "$N"; done
peer_bytes(){
  local c="$1"; docker exec "$c" sh -c 'du -sk /var/hyperledger/production 2>/dev/null | awk "{print \$1*1024}"' 2>/dev/null || return 1
}
echo 'redactions,peer1_bytes,peer2_bytes,total_bytes,delta_bytes,bytes_per_redaction,status' > "$OUT/f5_storage_growth.csv"
base=''; doneN=0
for target in 0 10 25 50; do
  if [ "$target" -gt "$doneN" ]; then
    for ((i=doneN+1;i<=target;i++)); do p=$(submit_payload "f5-r-$i" "f5-e-$i" "$N"); invoke "$p"; done
  fi
  sleep 1
  if p1=$(peer_bytes peer0.org1.example.com) && p2=$(peer_bytes peer0.org2.example.com); then
    total=$((p1+p2)); [ -z "$base" ] && base=$total; delta=$((total-base)); bpr=0; [ "$target" -gt 0 ] && bpr=$(awk -v d="$delta" -v n="$target" 'BEGIN{printf "%.3f",d/n}')
    echo "$target,$p1,$p2,$total,$delta,$bpr,MEASURED" >> "$OUT/f5_storage_growth.csv"
  else
    echo "$target,,,,,,SKIPPED_DU_UNAVAILABLE" >> "$OUT/f5_storage_growth.csv"
  fi
  doneN=$target
done

# A2: expanded Fabric attack tests.
echo 'test,expected,observed,pass,detail,status' > "$OUT/f6_adversarial.csv"
record_reject(){ local name="$1" payload="$2"; local out rc; set +e; out=$(invoke_capture "$payload"); rc=$?; set -e; local obs pass; if [ $rc -eq 0 ]; then obs=ACCEPT; pass=false; else obs=REJECT; pass=true; fi; detail=$(echo "$out" | tr '\n' ' ' | tr ',' ';' | tail -c 600); printf '%s,REJECT,%s,%s,"%s",MEASURED\n' "$name" "$obs" "$pass" "${detail//\"/\'}" >> "$OUT/f6_adversarial.csv"; }

# tampered proof
proof=$(proof_var "$N"); pub=$(public_var "$N"); red=$(fixture_var "$N" redacted_poseidon)
badproof=$(python - "$PROJECT/snark_results/n$N/proof_0.json" <<'PY'
import json,sys
p=json.load(open(sys.argv[1])); p['pi_a'][0]=str(int(p['pi_a'][0])+1); print(json.dumps(p,separators=(',',':')))
PY
)
register_ev f6-e-proof "$N"; record_reject tampered_groth16_proof "$(jq -cn --arg a SubmitRedaction --arg rid f6-r-badproof --arg eid f6-e-proof --arg cid "mask-$N" --arg rc "$red" --arg pol MASK-50-v1 --arg pr "$badproof" --arg pu "$pub" '{Args:[$a,$rid,$eid,$cid,$rc,$pol,$pr,$pu]}')"
# valid proof but wrong redacted argument
register_ev f6-e-red "$N"; wrongred=$(python -c "print(int('$red')+1)"); record_reject wrong_redacted_commitment "$(jq -cn --arg a SubmitRedaction --arg rid f6-r-wrongred --arg eid f6-e-red --arg cid "mask-$N" --arg rc "$wrongred" --arg pol MASK-50-v1 --arg pr "$proof" --arg pu "$pub" '{Args:[$a,$rid,$eid,$cid,$rc,$pol,$pr,$pu]}')"
# valid proof but a policy identifier not bound to the enforced 50% rule
register_ev f6-e-policy "$N"; record_reject wrong_policy_id "$(jq -cn --arg a SubmitRedaction --arg rid f6-r-wrongpolicy --arg eid f6-e-policy --arg cid "mask-$N" --arg rc "$red" --arg pol PII-v1 --arg pr "$proof" --arg pu "$pub" '{Args:[$a,$rid,$eid,$cid,$rc,$pol,$pr,$pu]}')"
# cross-evidence replay: proof verifies but evidence anchor differs
orig=$(fixture_var "$N" original_poseidon); ctx=$(fixture_var "$N" context); sha=$(fixture_var "$N" original_sha256); mr=$(fixture_var "$N" merkle_root); otherorig=$(python -c "print(int('$orig')+1)")
invoke "$(jq -cn --arg a RegisterEvidence --arg id f6-e-other --arg sha "$sha" --arg op "$otherorig" --arg ctx "$ctx" --arg mr "$mr" --arg meta '{}' '{Args:[$a,$id,$sha,$op,$ctx,$mr,$meta]}')"
record_reject cross_evidence_replay "$(jq -cn --arg a SubmitRedaction --arg rid f6-r-replay --arg eid f6-e-other --arg cid "mask-$N" --arg rc "$red" --arg pol MASK-50-v1 --arg pr "$proof" --arg pu "$pub" '{Args:[$a,$rid,$eid,$cid,$rc,$pol,$pr,$pu]}')"
# public signal tamper
badpub=$(python - "$PROJECT/snark_results/n$N/public_0.json" <<'PY'
import json,sys
x=json.load(open(sys.argv[1])); x[3]=str(int(x[3])+1); print(json.dumps(x,separators=(',',':')))
PY
)
register_ev f6-e-pub "$N"; record_reject tampered_public_signal "$(jq -cn --arg a SubmitRedaction --arg rid f6-r-badpub --arg eid f6-e-pub --arg cid "mask-$N" --arg rc "$red" --arg pol MASK-50-v1 --arg pr "$proof" --arg pu "$badpub" '{Args:[$a,$rid,$eid,$cid,$rc,$pol,$pr,$pu]}')"
# wrong verifier key/circuit id
register_ev f6-e-cid "$N"; othercid=mask-64; [ "$N" = 64 ] && othercid=mask-128; record_reject wrong_verifier_key "$(jq -cn --arg a SubmitRedaction --arg rid f6-r-wrongcid --arg eid f6-e-cid --arg cid "$othercid" --arg rc "$red" --arg pol MASK-50-v1 --arg pr "$proof" --arg pu "$pub" '{Args:[$a,$rid,$eid,$cid,$rc,$pol,$pr,$pu]}')"
# quorum tests helper
new_req(){ local id="$1"; register_ev "${id}-e" "$N"; invoke "$(submit_payload "${id}-r" "${id}-e" "$N")"; }
new_req f6-one; set_identity I; invoke "$(jq -cn --arg a ApproveRedaction --arg rid f6-one-r '{Args:[$a,$rid]}')"; record_reject one_of_four_commit "$(jq -cn --arg a CommitRedaction --arg rid f6-one-r '{Args:[$a,$rid]}')"
new_req f6-two; for role in I P; do set_identity "$role"; invoke "$(jq -cn --arg a ApproveRedaction --arg rid f6-two-r '{Args:[$a,$rid]}')"; done; record_reject two_of_four_commit "$(jq -cn --arg a CommitRedaction --arg rid f6-two-r '{Args:[$a,$rid]}')"
new_req f6-dup; set_identity I; invoke "$(jq -cn --arg a ApproveRedaction --arg rid f6-dup-r '{Args:[$a,$rid]}')"; invoke "$(jq -cn --arg a ApproveRedaction --arg rid f6-dup-r '{Args:[$a,$rid]}')"; set_identity P; invoke "$(jq -cn --arg a ApproveRedaction --arg rid f6-dup-r '{Args:[$a,$rid]}')"; record_reject duplicate_role_not_extra_vote "$(jq -cn --arg a CommitRedaction --arg rid f6-dup-r '{Args:[$a,$rid]}')"
new_req f6-unauth; set_identity U; record_reject unauthorized_certificate_approval "$(jq -cn --arg a ApproveRedaction --arg rid f6-unauth-r '{Args:[$a,$rid]}')"
# duplicate redaction id
set_identity I; register_ev f6-e-dup-id "$N"; p=$(submit_payload f6-r-dup-id f6-e-dup-id "$N"); invoke "$p"; record_reject duplicate_redaction_id "$p"
# stale-version conflict: two requests submitted at same version, first committed, second rejected.
register_ev f6-e-stale "$N"; invoke "$(submit_payload f6-r-stale-a f6-e-stale "$N")"; invoke "$(submit_payload f6-r-stale-b f6-e-stale "$N")"
for role in I P C; do set_identity "$role"; invoke "$(jq -cn --arg a ApproveRedaction --arg rid f6-r-stale-a '{Args:[$a,$rid]}')"; done; set_identity D; invoke "$(jq -cn --arg a CommitRedaction --arg rid f6-r-stale-a '{Args:[$a,$rid]}')"
for role in I P C; do set_identity "$role"; invoke "$(jq -cn --arg a ApproveRedaction --arg rid f6-r-stale-b '{Args:[$a,$rid]}')"; done; set_identity D; record_reject stale_version_rollback_conflict "$(jq -cn --arg a CommitRedaction --arg rid f6-r-stale-b '{Args:[$a,$rid]}')"

query "$(jq -cn --arg a GetAuditLog --arg id f6-e-stale '{Args:[$a,$id]}')" > "$OUT/f6_stale_audit.json" || true

# F7: true end-to-end workflow including fresh witness + Groth16 proof generation and on-ledger 3/4 commit.
echo 'size_B,rep,witness_ms,prove_ms,submit_ms,approvals_ms,commit_ms,end_to_end_ms,status' > "$OUT/f7_true_end_to_end.csv"
SNARKJS="$PROJECT/node_modules/.bin/snarkjs"; E2E_REPS="${FABRIC_PAPER_E2E_REPS:-3}"
for EN in 1024 4096; do
  [ -d "$PROJECT/snark_results/n$EN" ] || continue
  ED="$PROJECT/snark_results/n$EN"; JS="$ED/mask_${EN}_js"; WASM="$JS/mask_${EN}.wasm"; ZKEY="$ED/circuit_final.zkey"
  for ((r=1;r<=E2E_REPS;r++)); do
    eid="f7-e-$EN-$r"; rid="f7-r-$EN-$r"; set_identity I; register_ev "$eid" "$EN"
    w="$OUT/f7_${EN}_${r}.wtns"; pr="$OUT/f7_${EN}_${r}_proof.json"; pu="$OUT/f7_${EN}_${r}_public.json"
    total0=$(date +%s%N)
    t0=$(date +%s%N); node "$JS/generate_witness.js" "$WASM" "$ED/input.json" "$w" >/dev/null; t1=$(date +%s%N); wm=$(msdiff $((t1-t0)))
    t0=$(date +%s%N); "$SNARKJS" groth16 prove "$ZKEY" "$w" "$pr" "$pu" >/dev/null; t1=$(date +%s%N); pm=$(msdiff $((t1-t0)))
    pproof=$(jq -c . "$pr"); ppub=$(jq -c . "$pu"); pred=$(jq -r '.[1]' "$pu")
    payload=$(jq -cn --arg a SubmitRedaction --arg rid "$rid" --arg eid "$eid" --arg cid "mask-$EN" --arg rc "$pred" --arg pol MASK-50-v1 --arg pr "$pproof" --arg pu "$ppub" '{Args:[$a,$rid,$eid,$cid,$rc,$pol,$pr,$pu]}')
    t0=$(date +%s%N); invoke "$payload"; t1=$(date +%s%N); sm=$(msdiff $((t1-t0)))
    app0=$(date +%s%N); for role in I P C; do set_identity "$role"; invoke "$(jq -cn --arg a ApproveRedaction --arg rid "$rid" '{Args:[$a,$rid]}')"; done; app1=$(date +%s%N); am=$(msdiff $((app1-app0)))
    set_identity D; t0=$(date +%s%N); invoke "$(jq -cn --arg a CommitRedaction --arg rid "$rid" '{Args:[$a,$rid]}')"; t1=$(date +%s%N); cm=$(msdiff $((t1-t0))); total1=$(date +%s%N)
    echo "$EN,$r,$wm,$pm,$sm,$am,$cm,$(msdiff $((total1-total0))),MEASURED_TRUE_E2E" >> "$OUT/f7_true_end_to_end.csv"
  done
done
docker ps --format '{{.Names}},{{.Image}},{{.Status}}' > "$OUT/docker_state.csv"
peer channel getinfo -c "$FABRIC_CHANNEL" > "$OUT/channel_info.txt"
if [ "${KEEP_FABRIC_UP:-0}" != 1 ]; then ./network.sh down; fi
