$ErrorActionPreference='Stop'
$Root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
function Distro { $x=(& wsl.exe -l -q 2>$null|Out-String)-replace "`0",''; $a=$x -split "`r?`n"|%{$_.Trim()}|?{$_}; foreach($n in $a){if($n -eq 'Ubuntu-24.04'){return $n}}; foreach($n in $a){if($n -match '^Ubuntu'){return $n}}; throw 'Ubuntu WSL not found' }
function WPath([string]$p){$f=[IO.Path]::GetFullPath($p); if($f -notmatch '^([A-Za-z]):\\(.*)$'){throw "Unsupported path $f"}; "/mnt/$($matches[1].ToLower())/$(($matches[2]-replace '\\','/'))"}
$d=Distro; $src=WPath $Root; New-Item -ItemType Directory -Force -Path (Join-Path $Root 'results')|Out-Null; $wr=WPath (Join-Path $Root 'results')
& wsl.exe -d $d -u root -- bash -lc "tar -C '$src' --exclude='./results' -cf - benchmarks paper scripts config 2>/dev/null | tar -C /root/seal-coc --no-same-owner -xf - && bash /root/seal-coc/scripts/linux/generate_paper_only.sh '$wr'"
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
Start-Process explorer.exe (Join-Path $Root 'results\paper_ready')
