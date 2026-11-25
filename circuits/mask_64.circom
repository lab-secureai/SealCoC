pragma circom 2.2.0;
include "./valid_mask.circom";
component main {public [context, maxMask]} = ValidMask(64, 3);
