#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; source "$PROJECT/config/config.env"
PUB="$PROJECT/datasets/public"; ROOTD="$PROJECT/datasets/generated_ext4_root"; mkdir -p "$PUB" "$PROJECT/datasets/input"
CIC="$PUB/CICIDS2017_Friday_DDoS.csv"
CIC_URL='https://raw.githubusercontent.com/Brotherscodes/Cyber_Security_Intrusion_Prevention/eaa09e58937f90cd2a0c7fbf72d6ace8e251fddd/Resources/Friday-WorkingHours-Afternoon-DDos.pcap_ISCX.csv'
if [ ! -s "$CIC" ]; then echo 'Downloading pinned CIC-IDS2017 mirror (~155 MB)...'; curl -fL --retry 5 --retry-delay 2 -o "$CIC.part" "$CIC_URL"; mv "$CIC.part" "$CIC"; fi
# Build a deterministic binary EXT4 image without loop-mounting. This is deliberately labeled synthetic in all outputs.
IMG="$PUB/seal_synthetic_ext4.img"; MIB="${FINAL_BINARY_IMAGE_MIB:-128}"
if [ ! -s "$IMG" ]; then
  rm -rf "$ROOTD"; mkdir -p "$ROOTD/var/log" "$ROOTD/home/evidence" "$ROOTD/tmp"
  python3 - "$ROOTD" <<'PY'
from pathlib import Path
import random,sys
r=Path(sys.argv[1]); rng=random.Random(20261017)
with (r/'var/log/auth.log').open('w') as f:
    for i in range(20000): f.write(f'2026-10-17T12:{i%60:02d}:00Z sshd user=user{i%5000} src=10.{(i//65536)%256}.{(i//256)%256}.{i%256} action={"login" if i%7 else "failed"}\n')
with (r/'home/evidence/users.csv').open('w') as f:
    f.write('id,email,ip,action\n')
    for i in range(5000): f.write(f'{i},user{i}@example.invalid,192.0.2.{i%254+1},{"view" if i%3 else "download"}\n')
with (r/'home/evidence/binary.dat').open('wb') as f:
    for _ in range(8*1024): f.write(rng.getrandbits(64).to_bytes(8,'little'))
PY
  truncate -s "${MIB}M" "$IMG"; mkfs.ext4 -q -F -d "$ROOTD" "$IMG"
fi
