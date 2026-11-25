pragma circom 2.2.0;

include "circomlib/circuits/poseidon.circom";
include "circomlib/circuits/bitify.circom";
include "circomlib/circuits/comparators.circom";

// SEAL-CoC valid-masking circuit.
// - orig/red are private witnesses.
// - mask[i]=1 means byte i must be replaced by MASK_BYTE (42='*').
// - cOrig/cRed are public outputs; the application compares cOrig to the
//   immutable acquisition commitment and cRed to the delivered artifact.
// - context and maxMask are public inputs to prevent cross-case/version replay
//   and to demonstrate a simple enforceable redaction policy.
// - 31 bytes are packed per BN254 field before Poseidon chaining, which keeps
//   the circuit practical for 4 KiB segments.

template ValidMask(N, NC) {
    var MASK_BYTE = 42;

    signal input orig[N];
    signal input red[N];
    signal input mask[N];
    signal input rhoOrig;
    signal input rhoRed;
    signal input context;
    signal input maxMask;

    signal output cOrig;
    signal output cRed;
    signal output maskCount;

    component origBits[N];
    var msum = 0;
    for (var i = 0; i < N; i++) {
        // Byte-range constrain original evidence.
        origBits[i] = Num2Bits(8);
        origBits[i].in <== orig[i];

        // Boolean mask and mask-only transformation predicate.
        mask[i] * (mask[i] - 1) === 0;
        red[i] === orig[i] * (1 - mask[i]) + MASK_BYTE * mask[i];
        msum += mask[i];
    }
    maskCount <== msum;

    component policy = LessEqThan(16);
    policy.in[0] <== maskCount;
    policy.in[1] <== maxMask;
    policy.out === 1;

    signal packedOrig[NC];
    signal packedRed[NC];
    for (var c = 0; c < NC; c++) {
        var eo = 0;
        var er = 0;
        var coeff = 1;
        for (var j = 0; j < 31; j++) {
            var idx = c * 31 + j;
            if (idx < N) {
                eo += orig[idx] * coeff;
                er += red[idx] * coeff;
            }
            coeff *= 256;
        }
        packedOrig[c] <== eo;
        packedRed[c] <== er;
    }

    signal stateOrig[NC + 1];
    signal stateRed[NC + 1];
    component initO = Poseidon(2);
    component initR = Poseidon(2);
    initO.inputs[0] <== rhoOrig;
    initO.inputs[1] <== context;
    initR.inputs[0] <== rhoRed;
    initR.inputs[1] <== context;
    stateOrig[0] <== initO.out;
    stateRed[0] <== initR.out;

    component hO[NC];
    component hR[NC];
    for (var c2 = 0; c2 < NC; c2++) {
        hO[c2] = Poseidon(2);
        hR[c2] = Poseidon(2);
        hO[c2].inputs[0] <== stateOrig[c2];
        hO[c2].inputs[1] <== packedOrig[c2];
        hR[c2].inputs[0] <== stateRed[c2];
        hR[c2].inputs[1] <== packedRed[c2];
        stateOrig[c2 + 1] <== hO[c2].out;
        stateRed[c2 + 1] <== hR[c2].out;
    }

    component finalO = Poseidon(2);
    component finalR = Poseidon(2);
    finalO.inputs[0] <== stateOrig[NC];
    finalO.inputs[1] <== N;
    finalR.inputs[0] <== stateRed[NC];
    finalR.inputs[1] <== N;
    cOrig <== finalO.out;
    cRed <== finalR.out;
}
