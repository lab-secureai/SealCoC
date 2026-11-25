#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$PROJECT/config/config.env"
source "$PROJECT/.venv/bin/activate"
FABRIC_HOME="$PROJECT/third_party/fabric-samples"
NETWORK="$FABRIC_HOME/test-network"
OUT="$PROJECT/results/fabric"
mkdir -p "$OUT"
export PATH="$FABRIC_HOME/bin:$PATH"
export FABRIC_CFG_PATH="$FABRIC_HOME/config"

cd "$NETWORK"
./network.sh down || true
./network.sh up createChannel -ca -c "$FABRIC_CHANNEL"

# Vendor deps before Fabric packages the chaincode.
(cd "$PROJECT/chaincode/sealcoc" && go mod tidy && go mod vendor)
./network.sh deployCC -c "$FABRIC_CHANNEL" -ccn "$FABRIC_CC_NAME" -ccp "$PROJECT/chaincode/sealcoc" -ccl go -ccv "$FABRIC_CC_VERSION" -ccs "$FABRIC_CC_SEQUENCE"

ORDERER_CA="$NETWORK/organizations/ordererOrganizations/example.com/orderers/orderer.example.com/msp/tlscacerts/tlsca.example.com-cert.pem"
ORG1_CA="$NETWORK/organizations/peerOrganizations/org1.example.com/peers/peer0.org1.example.com/tls/ca.crt"
ORG2_CA="$NETWORK/organizations/peerOrganizations/org2.example.com/peers/peer0.org2.example.com/tls/ca.crt"
CA1="$NETWORK/organizations/fabric-ca/org1/ca-cert.pem"
CA2="$NETWORK/organizations/fabric-ca/org2/ca-cert.pem"

register_user(){
  local org="$1" name="$2" secret="$3" role="$4" port="$5" caname="$6"
  local orgdir="$NETWORK/organizations/peerOrganizations/org${org}.example.com"
  local ca="$NETWORK/organizations/fabric-ca/org${org}/ca-cert.pem"
  local home="$orgdir"
  export FABRIC_CA_CLIENT_HOME="$home"
  fabric-ca-client register --caname "$caname" --id.name "$name" --id.secret "$secret" --id.type client --id.attrs "seal.role=${role}:ecert" --tls.certfiles "$ca" >/dev/null 2>&1 || true
  local userdir="$orgdir/users/${name}@org${org}.example.com/msp"
  rm -rf "$userdir"
  fabric-ca-client enroll -u "https://${name}:${secret}@localhost:${port}" --caname "$caname" -M "$userdir" --tls.certfiles "$ca" >/dev/null
  cp "$orgdir/msp/config.yaml" "$userdir/config.yaml"
}
register_user 1 investigator investigatorpw I 7054 ca-org1
register_user 1 prosecutor prosecutorpw P 7054 ca-org1
register_user 2 court courtpw C 8054 ca-org2
register_user 2 defense defensepw D 8054 ca-org2

set_identity(){
  local role="$1"
  case "$role" in
    I) export CORE_PEER_LOCALMSPID=Org1MSP CORE_PEER_MSPCONFIGPATH="$NETWORK/organizations/peerOrganizations/org1.example.com/users/investigator@org1.example.com/msp" CORE_PEER_ADDRESS=localhost:7051 CORE_PEER_TLS_ROOTCERT_FILE="$ORG1_CA" ;;
    P) export CORE_PEER_LOCALMSPID=Org1MSP CORE_PEER_MSPCONFIGPATH="$NETWORK/organizations/peerOrganizations/org1.example.com/users/prosecutor@org1.example.com/msp" CORE_PEER_ADDRESS=localhost:7051 CORE_PEER_TLS_ROOTCERT_FILE="$ORG1_CA" ;;
    C) export CORE_PEER_LOCALMSPID=Org2MSP CORE_PEER_MSPCONFIGPATH="$NETWORK/organizations/peerOrganizations/org2.example.com/users/court@org2.example.com/msp" CORE_PEER_ADDRESS=localhost:9051 CORE_PEER_TLS_ROOTCERT_FILE="$ORG2_CA" ;;
    D) export CORE_PEER_LOCALMSPID=Org2MSP CORE_PEER_MSPCONFIGPATH="$NETWORK/organizations/peerOrganizations/org2.example.com/users/defense@org2.example.com/msp" CORE_PEER_ADDRESS=localhost:9051 CORE_PEER_TLS_ROOTCERT_FILE="$ORG2_CA" ;;
    *) echo "unknown role $role" >&2; return 2;;
  esac
  export CORE_PEER_TLS_ENABLED=true
}

invoke(){
  local payload="$1"
  peer chaincode invoke -o localhost:7050 --ordererTLSHostnameOverride orderer.example.com --tls --cafile "$ORDERER_CA" \
    -C "$FABRIC_CHANNEL" -n "$FABRIC_CC_NAME" \
    --peerAddresses localhost:7051 --tlsRootCertFiles "$ORG1_CA" \
    --peerAddresses localhost:9051 --tlsRootCertFiles "$ORG2_CA" \
    -c "$payload" --waitForEvent >/dev/null
}
query(){
  local payload="$1"
  peer chaincode query -C "$FABRIC_CHANNEL" -n "$FABRIC_CC_NAME" -c "$payload"
}

SDIR="$PROJECT/snark_results/n${FABRIC_CIRCUIT_SIZE}"
[ -f "$SDIR/proof_0.json" ] || { echo "Missing SNARK fixture $SDIR" >&2; exit 10; }
python "$PROJECT/fabric/prepare_fixture.py" --dir "$SDIR" --out "$OUT/fixture.json" >/dev/null
VK="$(jq -c . "$SDIR/verification_key.json")"
PROOF="$(jq -c . "$SDIR/proof_0.json")"
PUBLIC="$(jq -c . "$SDIR/public_0.json")"
ORIG_SHA="$(jq -r .original_sha256 "$OUT/fixture.json")"
ORIG_POSEIDON="$(jq -r .original_poseidon "$OUT/fixture.json")"
RED_POSEIDON="$(jq -r .redacted_poseidon "$OUT/fixture.json")"
CONTEXT="$(jq -r .context "$OUT/fixture.json")"
MERKLE="$(jq -r .merkle_root "$OUT/fixture.json")"
META="$(jq -c .metadata "$OUT/fixture.json" | jq -r .)"
CIRCUIT_ID="mask-${FABRIC_CIRCUIT_SIZE}"

set_identity I
invoke "$(jq -cn --arg a SetVerifierKey --arg id "$CIRCUIT_ID" --arg vk "$VK" '{Args:[$a,$id,$vk]}')"
invoke "$(jq -cn --arg a RegisterEvidence --arg id evidence-main --arg sha "$ORIG_SHA" --arg op "$ORIG_POSEIDON" --arg ctx "$CONTEXT" --arg mr "$MERKLE" --arg meta "$META" '{Args:[$a,$id,$sha,$op,$ctx,$mr,$meta]}')"

# Raw Groth16 verification cost inside a Fabric peer (query/evaluate path).
echo 'rep,latency_ms,status' > "$OUT/fabric_verify_query.csv"
for ((i=1;i<=FABRIC_TX_REPS;i++)); do
  p="$(jq -cn --arg a VerifyOnly --arg cid "$CIRCUIT_ID" --arg pr "$PROOF" --arg pu "$PUBLIC" '{Args:[$a,$cid,$pr,$pu]}')"
  t0=$(date +%s%N); query "$p" >/dev/null; t1=$(date +%s%N)
  echo "$i,$(awk -v d=$((t1-t0)) 'BEGIN{printf "%.3f",d/1000000}'),OK" >> "$OUT/fabric_verify_query.csv"
done

# End-to-end ordered SubmitRedaction: Groth16 verification + endorsement + ordering + commit.
echo 'rep,latency_ms,status' > "$OUT/fabric_submit_tx.csv"
for ((i=1;i<=FABRIC_TX_REPS;i++)); do
  rid="red-seq-$i"
  p="$(jq -cn --arg a SubmitRedaction --arg rid "$rid" --arg eid evidence-main --arg cid "$CIRCUIT_ID" --arg rc "$RED_POSEIDON" --arg pol MASK-50-v1 --arg pr "$PROOF" --arg pu "$PUBLIC" '{Args:[$a,$rid,$eid,$cid,$rc,$pol,$pr,$pu]}')"
  t0=$(date +%s%N); invoke "$p"; t1=$(date +%s%N)
  echo "$i,$(awk -v d=$((t1-t0)) 'BEGIN{printf "%.3f",d/1000000}'),OK" >> "$OUT/fabric_submit_tx.csv"
done

# A real certificate-bound 3-of-4 approval and commit.
RID=red-seq-1
for role in I P C; do
  set_identity "$role"
  invoke "$(jq -cn --arg a ApproveRedaction --arg rid "$RID" '{Args:[$a,$rid]}')"
done
set_identity D
invoke "$(jq -cn --arg a CommitRedaction --arg rid "$RID" '{Args:[$a,$rid]}')"
query "$(jq -cn --arg a GetRedaction --arg rid "$RID" '{Args:[$a,$rid]}')" > "$OUT/committed_redaction.json"
query "$(jq -cn --arg a GetEvidence --arg id evidence-main '{Args:[$a,$id]}')" > "$OUT/evidence_after_commit.json"
query "$(jq -cn --arg a GetAuditLog --arg id evidence-main '{Args:[$a,$id]}')" > "$OUT/audit_log.json"

# Adversarial Fabric checks: bad proof and insufficient quorum must be rejected.
echo 'test,expected,observed,pass' > "$OUT/fabric_adversarial.csv"
BADPROOF="$(python - "$SDIR/proof_0.json" <<'PY'
import json,sys
p=json.load(open(sys.argv[1])); p['pi_a'][0]=str(int(p['pi_a'][0])+1); print(json.dumps(p,separators=(',',':')))
PY
)"
set_identity I
bad_payload="$(jq -cn --arg a SubmitRedaction --arg rid red-bad-proof --arg eid evidence-main --arg cid "$CIRCUIT_ID" --arg rc "$RED_POSEIDON" --arg pol MASK-50-v1 --arg pr "$BADPROOF" --arg pu "$PUBLIC" '{Args:[$a,$rid,$eid,$cid,$rc,$pol,$pr,$pu]}')"
if invoke "$bad_payload" >/dev/null 2>&1; then obs=ACCEPT; pass=false; else obs=REJECT; pass=true; fi
echo "tampered_groth16_proof,REJECT,$obs,$pass" >> "$OUT/fabric_adversarial.csv"

# Create a fresh valid request, approve with only two roles, and verify commit rejection.
invoke "$(jq -cn --arg a SubmitRedaction --arg rid red-two-quorum --arg eid evidence-main --arg cid "$CIRCUIT_ID" --arg rc "$RED_POSEIDON" --arg pol MASK-50-v1 --arg pr "$PROOF" --arg pu "$PUBLIC" '{Args:[$a,$rid,$eid,$cid,$rc,$pol,$pr,$pu]}')"
for role in I P; do set_identity "$role"; invoke "$(jq -cn --arg a ApproveRedaction --arg rid red-two-quorum '{Args:[$a,$rid]}')"; done
if invoke "$(jq -cn --arg a CommitRedaction --arg rid red-two-quorum '{Args:[$a,$rid]}')" >/dev/null 2>&1; then obs=ACCEPT; pass=false; else obs=REJECT; pass=true; fi
echo "two_of_four_commit,REJECT,$obs,$pass" >> "$OUT/fabric_adversarial.csv"

# Concurrency throughput: separate evidence keys avoid the single-audit-key MVCC hotspot.
set_identity I
for ((i=1;i<=FABRIC_THROUGHPUT_TX;i++)); do
  invoke "$(jq -cn --arg a RegisterEvidence --arg id "bench-e-$i" --arg sha "$ORIG_SHA" --arg op "$ORIG_POSEIDON" --arg ctx "$CONTEXT" --arg mr "$MERKLE" --arg meta '{}' '{Args:[$a,$id,$sha,$op,$ctx,$mr,$meta]}')"
done
export -f invoke query set_identity
export FABRIC_CHANNEL FABRIC_CC_NAME ORDERER_CA ORG1_CA ORG2_CA NETWORK CIRCUIT_ID RED_POSEIDON PROOF PUBLIC
start=$(date +%s%N)
failfile="$OUT/concurrency_failures.txt"; : > "$failfile"
for ((i=1;i<=FABRIC_THROUGHPUT_TX;i++)); do
  (
    rid="red-par-$i"; eid="bench-e-$i"
    p="$(jq -cn --arg a SubmitRedaction --arg rid "$rid" --arg eid "$eid" --arg cid "$CIRCUIT_ID" --arg rc "$RED_POSEIDON" --arg pol MASK-50-v1 --arg pr "$PROOF" --arg pu "$PUBLIC" '{Args:[$a,$rid,$eid,$cid,$rc,$pol,$pr,$pu]}')"
    invoke "$p" || echo "$i" >> "$failfile"
  ) &
  while [ "$(jobs -pr | wc -l)" -ge "$FABRIC_CONCURRENCY" ]; do sleep 0.05; done
done
wait
end=$(date +%s%N)
elapsed_ns=$((end-start)); fails=$(wc -l < "$failfile"); ok=$((FABRIC_THROUGHPUT_TX-fails))
throughput=$(awk -v n="$ok" -v d="$elapsed_ns" 'BEGIN{printf "%.3f", n/(d/1000000000)}')
elapsed_ms=$(awk -v d="$elapsed_ns" 'BEGIN{printf "%.3f",d/1000000}')
printf 'transactions,concurrency,successful,failed,elapsed_ms,throughput_tx_s\n%s,%s,%s,%s,%s,%s\n' "$FABRIC_THROUGHPUT_TX" "$FABRIC_CONCURRENCY" "$ok" "$fails" "$elapsed_ms" "$throughput" > "$OUT/fabric_throughput.csv"

docker ps --format '{{.Names}},{{.Image}},{{.Status}}' > "$OUT/docker_network_state.csv"
peer channel getinfo -c "$FABRIC_CHANNEL" > "$OUT/channel_info.txt"

if [ "$KEEP_FABRIC_UP" != "1" ]; then ./network.sh down; fi
