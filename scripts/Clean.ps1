$ErrorActionPreference='Continue'
$Root = Split-Path -Parent $PSScriptRoot
$cfg = Join-Path $Root 'config\config.env'
$Distro = ((Get-Content $cfg | Where-Object {$_ -match '^WSL_DISTRO='}) -split '=',2)[1].Trim()
Write-Host 'Stopping SEAL-CoC Fabric network and removing WSL-side working copy...'
wsl.exe -d $Distro -u root -- bash -lc "if [ -d /root/seal-coc/third_party/fabric-samples/test-network ]; then cd /root/seal-coc/third_party/fabric-samples/test-network && ./network.sh down || true; fi; rm -rf /root/seal-coc"
Write-Host 'Done. WSL distribution and system packages were intentionally kept.'
