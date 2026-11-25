package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/hyperledger/fabric-contract-api-go/contractapi"
	rapidtypes "github.com/iden3/go-rapidsnark/types"
	rapidverifier "github.com/iden3/go-rapidsnark/verifier"
)

type SmartContract struct{ contractapi.Contract }

type Evidence struct {
	EvidenceID       string `json:"evidenceId"`
	OriginalSHA256   string `json:"originalSha256"`
	OriginalPoseidon string `json:"originalPoseidon"`
	ContextField     string `json:"contextField"`
	MerkleRoot       string `json:"merkleRoot"`
	MetadataJSON     string `json:"metadataJson"`
	CurrentVersion   string `json:"currentVersion"`
	CurrentCommit    string `json:"currentCommit"`
	CreatedTx        string `json:"createdTx"`
	CreatedAt        string `json:"createdAt"`
}

type Redaction struct {
	RedactionID      string   `json:"redactionId"`
	EvidenceID       string   `json:"evidenceId"`
	CircuitID        string   `json:"circuitId"`
	RedactedPoseidon string   `json:"redactedPoseidon"`
	PolicyID         string   `json:"policyId"`
	ProofJSON        string   `json:"proofJson"`
	PublicJSON       string   `json:"publicJson"`
	ProofHash        string   `json:"proofHash"`
	PreviousVersion  string   `json:"previousVersion"`
	Approvals        []string `json:"approvals"`
	Status           string   `json:"status"`
	SubmittedTx      string   `json:"submittedTx"`
	SubmittedAt      string   `json:"submittedAt"`
	CommittedTx      string   `json:"committedTx"`
	CommittedAt      string   `json:"committedAt"`
}

func key(prefix, id string) string { return prefix + ":" + id }

func txTime(ctx contractapi.TransactionContextInterface) string {
	ts, err := ctx.GetStub().GetTxTimestamp()
	if err != nil {
		return time.Unix(0, 0).UTC().Format(time.RFC3339Nano)
	}
	return time.Unix(ts.Seconds, int64(ts.Nanos)).UTC().Format(time.RFC3339Nano)
}

func (s *SmartContract) SetVerifierKey(ctx contractapi.TransactionContextInterface, circuitID string, vkJSON string) error {
	if strings.TrimSpace(circuitID) == "" || strings.TrimSpace(vkJSON) == "" {
		return fmt.Errorf("circuitID and verification key are required")
	}
	var tmp map[string]interface{}
	if err := json.Unmarshal([]byte(vkJSON), &tmp); err != nil {
		return fmt.Errorf("invalid verification-key JSON: %w", err)
	}
	return ctx.GetStub().PutState(key("vk", circuitID), []byte(vkJSON))
}

func (s *SmartContract) RegisterEvidence(ctx contractapi.TransactionContextInterface, evidenceID, originalSHA256, originalPoseidon, contextField, merkleRoot, metadataJSON string) error {
	k := key("evidence", evidenceID)
	old, err := ctx.GetStub().GetState(k)
	if err != nil {
		return err
	}
	if old != nil {
		return fmt.Errorf("evidence %s already exists", evidenceID)
	}
	if evidenceID == "" || originalPoseidon == "" || contextField == "" {
		return fmt.Errorf("evidenceID, originalPoseidon and contextField are required")
	}
	initial := sha256.Sum256([]byte("SEAL-V0|" + evidenceID + "|" + originalPoseidon + "|" + merkleRoot))
	e := Evidence{EvidenceID: evidenceID, OriginalSHA256: originalSHA256, OriginalPoseidon: originalPoseidon, ContextField: contextField, MerkleRoot: merkleRoot, MetadataJSON: metadataJSON, CurrentVersion: hex.EncodeToString(initial[:]), CurrentCommit: originalPoseidon, CreatedTx: ctx.GetStub().GetTxID(), CreatedAt: txTime(ctx)}
	b, _ := json.Marshal(e)
	return ctx.GetStub().PutState(k, b)
}

func (s *SmartContract) GetEvidence(ctx contractapi.TransactionContextInterface, evidenceID string) (*Evidence, error) {
	b, err := ctx.GetStub().GetState(key("evidence", evidenceID))
	if err != nil {
		return nil, err
	}
	if b == nil {
		return nil, fmt.Errorf("evidence %s not found", evidenceID)
	}
	var e Evidence
	if err := json.Unmarshal(b, &e); err != nil {
		return nil, err
	}
	return &e, nil
}

func (s *SmartContract) verifyProof(ctx contractapi.TransactionContextInterface, circuitID, proofJSON, publicJSON string) ([]string, error) {
	vk, err := ctx.GetStub().GetState(key("vk", circuitID))
	if err != nil {
		return nil, err
	}
	if vk == nil {
		return nil, fmt.Errorf("verification key %s not found", circuitID)
	}
	var pd rapidtypes.ProofData
	if err := json.Unmarshal([]byte(proofJSON), &pd); err != nil {
		return nil, fmt.Errorf("invalid proof JSON: %w", err)
	}
	var pub []string
	if err := json.Unmarshal([]byte(publicJSON), &pub); err != nil {
		return nil, fmt.Errorf("invalid public signals JSON: %w", err)
	}
	zkp := rapidtypes.ZKProof{Proof: &pd, PubSignals: pub}
	if err := rapidverifier.VerifyGroth16(zkp, vk); err != nil {
		return nil, fmt.Errorf("Groth16 verification failed: %w", err)
	}
	return pub, nil
}

func (s *SmartContract) VerifyOnly(ctx contractapi.TransactionContextInterface, circuitID, proofJSON, publicJSON string) (bool, error) {
	_, err := s.verifyProof(ctx, circuitID, proofJSON, publicJSON)
	if err != nil {
		return false, err
	}
	return true, nil
}

func (s *SmartContract) SubmitRedaction(ctx contractapi.TransactionContextInterface, redactionID, evidenceID, circuitID, redactedPoseidon, policyID, proofJSON, publicJSON string) error {
	rk := key("redaction", redactionID)
	prev, err := ctx.GetStub().GetState(rk)
	if err != nil {
		return err
	}
	if prev != nil {
		return fmt.Errorf("redaction %s already exists", redactionID)
	}
	e, err := s.GetEvidence(ctx, evidenceID)
	if err != nil {
		return err
	}
	pub, err := s.verifyProof(ctx, circuitID, proofJSON, publicJSON)
	if err != nil {
		return err
	}
	// Circom public-signal order for this circuit: [cOrig,cRed,maskCount,context,maxMask].
	if len(pub) < 5 {
		return fmt.Errorf("expected at least 5 public signals, got %d", len(pub))
	}
	// This prototype implements one explicit, cryptographically enforced policy:
	// mask-only transformation with at most 50%% of the fixed-size segment masked.
	// Do not label this as semantic/regex PII detection; regex selection is an external workload step.
	if policyID != "MASK-50-v1" {
		return fmt.Errorf("unsupported policy %s; expected MASK-50-v1", policyID)
	}
	nStr := strings.TrimPrefix(circuitID, "mask-")
	n, perr := strconv.Atoi(nStr)
	if perr != nil || n <= 0 {
		return fmt.Errorf("invalid circuitID %s", circuitID)
	}
	expectedMaxMask := strconv.Itoa(n / 2)
	if pub[4] != expectedMaxMask {
		return fmt.Errorf("proof maxMask %s does not match policy maximum %s", pub[4], expectedMaxMask)
	}
	if pub[0] != e.OriginalPoseidon {
		return fmt.Errorf("proof is not bound to acquired original commitment")
	}
	if pub[1] != redactedPoseidon {
		return fmt.Errorf("redacted commitment does not match proof")
	}
	if pub[3] != e.ContextField {
		return fmt.Errorf("proof context does not match evidence context")
	}
	ph := sha256.Sum256([]byte(proofJSON + "\n" + publicJSON))
	r := Redaction{RedactionID: redactionID, EvidenceID: evidenceID, CircuitID: circuitID, RedactedPoseidon: redactedPoseidon, PolicyID: policyID, ProofJSON: proofJSON, PublicJSON: publicJSON, ProofHash: hex.EncodeToString(ph[:]), PreviousVersion: e.CurrentVersion, Approvals: []string{}, Status: "PROOF_VERIFIED", SubmittedTx: ctx.GetStub().GetTxID(), SubmittedAt: txTime(ctx)}
	b, _ := json.Marshal(r)
	if err := ctx.GetStub().PutState(rk, b); err != nil {
		return err
	}
	return s.appendAudit(ctx, evidenceID, redactionID)
}

func (s *SmartContract) GetRedaction(ctx contractapi.TransactionContextInterface, redactionID string) (*Redaction, error) {
	b, err := ctx.GetStub().GetState(key("redaction", redactionID))
	if err != nil {
		return nil, err
	}
	if b == nil {
		return nil, fmt.Errorf("redaction %s not found", redactionID)
	}
	var r Redaction
	if err := json.Unmarshal(b, &r); err != nil {
		return nil, err
	}
	return &r, nil
}

func (s *SmartContract) ApproveRedaction(ctx contractapi.TransactionContextInterface, redactionID string) error {
	actor, found, err := ctx.GetClientIdentity().GetAttributeValue("seal.role")
	if err != nil {
		return fmt.Errorf("cannot read seal.role attribute: %w", err)
	}
	allowed := map[string]bool{"I": true, "P": true, "C": true, "D": true}
	if !found || !allowed[actor] {
		return fmt.Errorf("caller certificate must contain seal.role=I|P|C|D")
	}
	r, err := s.GetRedaction(ctx, redactionID)
	if err != nil {
		return err
	}
	if r.Status == "COMMITTED" {
		return fmt.Errorf("redaction already committed")
	}
	for _, a := range r.Approvals {
		if a == actor {
			return nil
		}
	}
	r.Approvals = append(r.Approvals, actor)
	sort.Strings(r.Approvals)
	b, _ := json.Marshal(r)
	return ctx.GetStub().PutState(key("redaction", redactionID), b)
}

func (s *SmartContract) CommitRedaction(ctx contractapi.TransactionContextInterface, redactionID string) error {
	r, err := s.GetRedaction(ctx, redactionID)
	if err != nil {
		return err
	}
	if r.Status == "COMMITTED" {
		return nil
	}
	if len(r.Approvals) < 3 {
		return fmt.Errorf("3-of-4 approval required; got %d", len(r.Approvals))
	}
	e, err := s.GetEvidence(ctx, r.EvidenceID)
	if err != nil {
		return err
	}
	if e.CurrentVersion != r.PreviousVersion {
		return fmt.Errorf("version conflict/rollback detected")
	}
	next := sha256.Sum256([]byte("SEAL-VN|" + r.PreviousVersion + "|" + r.RedactionID + "|" + r.RedactedPoseidon))
	e.CurrentVersion = hex.EncodeToString(next[:])
	e.CurrentCommit = r.RedactedPoseidon
	r.Status = "COMMITTED"
	r.CommittedTx = ctx.GetStub().GetTxID()
	r.CommittedAt = txTime(ctx)
	eb, _ := json.Marshal(e)
	rb, _ := json.Marshal(r)
	if err := ctx.GetStub().PutState(key("evidence", e.EvidenceID), eb); err != nil {
		return err
	}
	return ctx.GetStub().PutState(key("redaction", r.RedactionID), rb)
}

func (s *SmartContract) appendAudit(ctx contractapi.TransactionContextInterface, evidenceID, redactionID string) error {
	k := key("audit", evidenceID)
	b, err := ctx.GetStub().GetState(k)
	if err != nil {
		return err
	}
	var ids []string
	if b != nil {
		if err := json.Unmarshal(b, &ids); err != nil {
			return err
		}
	}
	ids = append(ids, redactionID)
	out, _ := json.Marshal(ids)
	return ctx.GetStub().PutState(k, out)
}

func (s *SmartContract) GetAuditLog(ctx contractapi.TransactionContextInterface, evidenceID string) ([]*Redaction, error) {
	b, err := ctx.GetStub().GetState(key("audit", evidenceID))
	if err != nil {
		return nil, err
	}
	if b == nil {
		return []*Redaction{}, nil
	}
	var ids []string
	if err := json.Unmarshal(b, &ids); err != nil {
		return nil, err
	}
	out := make([]*Redaction, 0, len(ids))
	for _, id := range ids {
		r, e := s.GetRedaction(ctx, id)
		if e != nil {
			return nil, e
		}
		out = append(out, r)
	}
	return out, nil
}

func main() {
	cc, err := contractapi.NewChaincode(&SmartContract{})
	if err != nil {
		panic(err)
	}
	if err := cc.Start(); err != nil {
		panic(err)
	}
}
