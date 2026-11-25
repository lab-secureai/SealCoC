$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
function Get-UbuntuDistro {
    $raw = & wsl.exe -l -q 2>$null | Out-String
    $raw = $raw -replace "`0", ""
    $names = $raw -split "`r?`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    foreach ($n in $names) { if ($n -eq 'Ubuntu-24.04') { return $n } }
    foreach ($n in $names) { if ($n -match '^Ubuntu') { return $n } }
    throw 'No Ubuntu WSL distro found. Run the previous installer first.'
}
function Convert-ToWslPath([string]$Path) {
    $full = [System.IO.Path]::GetFullPath($Path)
    if ($full -notmatch '^([A-Za-z]):\\(.*)$') { throw "Unsupported Windows path: $full" }
    $drive = $matches[1].ToLower(); $tail = $matches[2] -replace '\\','/'
    return "/mnt/$drive/$tail"
}
$distro = Get-UbuntuDistro
$src = Convert-ToWslPath $Root
$resultsWin = Join-Path $Root 'results'
New-Item -ItemType Directory -Force -Path $resultsWin | Out-Null
$winResults = Convert-ToWslPath $resultsWin
Write-Host "SEAL-CoC  Paper Experiment Suite" -ForegroundColor Cyan
Write-Host "Using WSL distro: $distro" -ForegroundColor Cyan
Write-Host "This will reuse prior SNARK artifacts where possible, then run the missing evaluation scenarios." -ForegroundColor Yellow
& wsl.exe -d $distro -u root -- bash "$src/scripts/linux/prepare_and_run_paper.sh" "$src" "$winResults"
$rc=$LASTEXITCODE
if($rc -ne 0){ Write-Host "`nPaper suite stopped with exit code $rc. Inspect results\progress.txt and results\logs." -ForegroundColor Red; exit $rc }
Write-Host "`nPaper-ready package created successfully." -ForegroundColor Green
Start-Process explorer.exe (Join-Path $resultsWin 'paper_ready')
