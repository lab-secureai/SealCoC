#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('All','Continue')]
    [string]$Mode = 'All'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Root = Split-Path -Parent $PSScriptRoot
$Log = Join-Path $Root 'windows_bootstrap.log'
$Results = Join-Path $Root 'results'
$StateDir = Join-Path $Root '.seal_state'
New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
New-Item -ItemType Directory -Path $Results -Force | Out-Null
Start-Transcript -Path $Log -Append | Out-Null

function Set-Progress([string]$Phase,[string]$Message) {
    $line = "$(Get-Date -Format o) | $Phase | $Message"
    $line | Set-Content -Path (Join-Path $Results 'progress.txt') -Encoding UTF8
    Write-Host "`n==> [$Phase] $Message" -ForegroundColor Cyan
}
function Write-Info([string]$Message) { Write-Host "    $Message" -ForegroundColor Gray }
function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
function Get-ConfigValue([string]$Name) {
    $cfg = Join-Path $Root 'config\config.env'
    $line = Get-Content $cfg | Where-Object { $_ -match "^$([regex]::Escape($Name))=" } | Select-Object -First 1
    if (-not $line) { throw "Missing $Name in $cfg" }
    return ($line -split '=',2)[1].Trim()
}
function Clear-OldResume {
    Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce' -Name 'SEALCoCResume' -ErrorAction SilentlyContinue
}
function Set-ResumeAfterReboot {
    $launcher = Join-Path $Root 'CONTINUE_AFTER_WSL.cmd'
    # RunOnce starts a normal CMD; CONTINUE_AFTER_WSL self-elevates and then runs the pipeline.
    $value = 'cmd.exe /d /c ""' + $launcher + '""'
    New-Item -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce' -Force | Out-Null
    New-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce' -Name 'SEALCoCResume' -Value $value -PropertyType String -Force | Out-Null
}
function Get-Distros {
    try {
        $raw = & wsl.exe -l -q 2>$null
        return @($raw | ForEach-Object { ($_ -replace "`0",'').Trim() } | Where-Object { $_ })
    } catch { return @() }
}

function Get-DistroVersion([string]$Name) {
    # wsl.exe output may contain UTF-16 NULs and a leading '*' for the default distro.
    # Parse the final numeric column from the exact distro row.
    try {
        $lines = & wsl.exe -l -v 2>$null
        foreach ($raw in $lines) {
            $line = (($raw -replace "`0",'').Trim())
            if (-not $line) { continue }
            $line = ($line -replace '^\*\s*','')
            if ($line -match ('^' + [regex]::Escape($Name) + '\s+.*\s+([12])\s*$')) {
                return [int]$Matches[1]
            }
        }
    } catch {}
    return 0
}
function Ensure-DistroWSL2([string]$Name) {
    $version = Get-DistroVersion $Name
    if ($version -eq 2) {
        Write-Info "${Name} is already WSL2; skipping wsl --set-version."
        return
    }
    if ($version -eq 0) {
        Write-Warning "Could not parse WSL version for '$Name'; checking after a safe shutdown."
    } else {
        Write-Info "${Name} is WSL$version; converting to WSL2."
    }

    # Conversion is not valid while the distro/WSL VM is in some running states.
    & wsl.exe --terminate $Name 2>$null | Out-Null
    Start-Sleep -Seconds 2
    $output = & wsl.exe --set-version $Name 2 2>&1
    $code = $LASTEXITCODE
    $output | Out-Host

    # WSL can occasionally return WSL_E_VM_MODE_INVALID_STATE even after saying
    # 'The distribution is already the requested version'. Trust the observed
    # final state rather than the process exit code alone.
    $finalVersion = Get-DistroVersion $Name
    if ($finalVersion -eq 2) {
        if ($code -ne 0) {
            Write-Warning "wsl --set-version returned code $code, but '$Name' is confirmed as WSL2; continuing."
        }
        return
    }

    Save-WSLDiagnostics $Name
    throw "Could not ensure '$Name' is WSL2 (detected version: $finalVersion). Run: wsl --shutdown ; wsl -l -v"
}


function Convert-WindowsPathToWSL([string]$WindowsPath,[string]$Distro) {
    # Prefer deterministic drive-letter conversion. This avoids a WSL/PowerShell
    # edge case where direct `wslpath` invocation can return no stdout even when
    # the distro is healthy (observed on WSL 2.6.x / Ubuntu 24.04).
    $full = [System.IO.Path]::GetFullPath($WindowsPath)
    if ($full -match '^([A-Za-z]):\\(.*)$') {
        $drive = ([string]$Matches[1]).ToLowerInvariant()
        $rest = ([string]$Matches[2]) -replace '\\','/'
        $candidate = "/mnt/$drive/$rest"
        & wsl.exe -d $Distro -u root -- test -d $candidate 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Info "Windows path mapped directly: $full -> $candidate"
            return $candidate
        }
        Write-Warning "Direct /mnt/$drive mapping did not resolve '$full'; falling back to wslpath."
    }

    # Fallback: execute wslpath inside bash and pass the Windows path as $1, so
    # quoting/backslashes/spaces are not interpreted by PowerShell or bash.
    $out = & wsl.exe -d $Distro -u root -- bash -lc 'wslpath -a "$1"' _ $full 2>&1
    $code = $LASTEXITCODE
    $lines = @($out | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ -match '^/' })
    if ($code -eq 0 -and $lines.Count -gt 0) {
        $resolved = [string]$lines[$lines.Count - 1]
        & wsl.exe -d $Distro -u root -- test -d $resolved 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Info "wslpath resolved: $full -> $resolved"
            return $resolved
        }
    }

    if ($out) { $out | Out-Host }
    Save-WSLDiagnostics $Distro
    throw "Could not translate/access Windows project path '$full' inside WSL. Expected a mount such as /mnt/c/..."
}

function Wait-ForDistro([string]$Name,[int]$Seconds=120) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        $installed = Get-Distros
        if ($installed -contains $Name) { return $true }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    return $false
}
function Invoke-WSLInstall([string]$Name,[bool]$WebDownload) {
    $args = @('--install','-d',$Name,'--no-launch')
    if ($WebDownload) { $args += '--web-download' }
    Write-Info ('Trying: wsl.exe ' + ($args -join ' '))
    $output = & wsl.exe @args 2>&1
    $code = $LASTEXITCODE
    $output | Out-Host
    return @{ Code=$code; Text=($output | Out-String) }
}
function Resolve-UbuntuDistro([string]$Preferred) {
    $installed = Get-Distros
    if ($installed -contains $Preferred) { return $Preferred }
    $existing = $installed | Where-Object { $_ -match '^Ubuntu' } | Select-Object -First 1
    if ($existing) {
        Write-Warning "Configured distro '$Preferred' is not installed; using existing '$existing'."
        return $existing
    }

    Set-Progress 'UBUNTU' "No Ubuntu distro is registered; installing $Preferred"
    $candidates = @($Preferred,'Ubuntu-24.04','Ubuntu') | Select-Object -Unique
    foreach ($candidate in $candidates) {
        foreach ($web in @($true,$false)) {
            $r = Invoke-WSLInstall $candidate $web
            if (Wait-ForDistro $candidate 90) { return $candidate }
            if ($r.Code -eq 3010) {
                throw "Ubuntu installer requested a reboot. Reboot Windows once, then double-click CONTINUE_AFTER_WSL.cmd."
            }
        }
    }
    Save-WSLDiagnostics ''
    throw "WSL is installed, but Ubuntu was not registered. Run CHECK_STATUS.cmd. You can also run in Administrator PowerShell: wsl --install -d Ubuntu-24.04 --web-download ; then run CONTINUE_AFTER_WSL.cmd."
}
function Enable-WSLFeatures {
    $features = @('Microsoft-Windows-Subsystem-Linux','VirtualMachinePlatform')
    $restartNeeded = $false
    foreach ($name in $features) {
        $f = Get-WindowsOptionalFeature -Online -FeatureName $name
        Write-Info "${name}: $($f.State)"
        if ($f.State -ne 'Enabled') {
            Set-Progress 'WINDOWS' "Enabling Windows feature $name"
            $result = Enable-WindowsOptionalFeature -Online -FeatureName $name -All -NoRestart
            if ($result.RestartNeeded) { $restartNeeded = $true }
        }
    }
    return $restartNeeded
}
function Save-WSLDiagnostics([string]$Distro) {
    $diag = Join-Path $Root 'wsl_diagnostics.txt'
    "Generated: $(Get-Date -Format o)" | Set-Content $diag
    "`n=== wsl --status ===" | Add-Content $diag
    (& wsl.exe --status 2>&1 | Out-String) | Add-Content $diag
    "`n=== wsl --version ===" | Add-Content $diag
    (& wsl.exe --version 2>&1 | Out-String) | Add-Content $diag
    "`n=== wsl -l -v ===" | Add-Content $diag
    (& wsl.exe -l -v 2>&1 | Out-String) | Add-Content $diag
    "`n=== wsl -l -o ===" | Add-Content $diag
    (& wsl.exe -l -o 2>&1 | Out-String) | Add-Content $diag
    if ($Distro) {
        "`n=== $Distro /etc/os-release ===" | Add-Content $diag
        (& wsl.exe -d $Distro -u root -- cat /etc/os-release 2>&1 | Out-String) | Add-Content $diag
    }
}

try {
    Clear-OldResume
    if (-not (Test-Admin)) { throw 'RUN_ALL.cmd/CONTINUE_AFTER_WSL.cmd must be allowed through the UAC Administrator prompt.' }

    $PreferredDistro = Get-ConfigValue 'WSL_DISTRO'
    $os = Get-CimInstance Win32_OperatingSystem
    $build = [int]$os.BuildNumber
    $ramGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
    Set-Progress 'WINDOWS' "Windows $($os.Caption) build $build; RAM $ramGB GB; mode=$Mode"
    if ($build -lt 19041) { throw "Windows build $build is too old for this WSL2 workflow." }
    if ($ramGB -lt 8) { Write-Warning 'Less than 8 GB RAM: 4 KiB Groth16 may fail or swap heavily.' }

    if ($Mode -eq 'All') {
        $restartNeeded = Enable-WSLFeatures
        if ($restartNeeded) {
            Set-ResumeAfterReboot
            Set-Progress 'REBOOT' 'WSL Windows features enabled; one reboot is required. Resume registered.'
            Write-Host "`nA Windows reboot is required once. The bundle will attempt to resume after login." -ForegroundColor Yellow
            Write-Host 'If it does not resume automatically, double-click CONTINUE_AFTER_WSL.cmd.' -ForegroundColor Yellow
            shutdown.exe /r /t 20 /c "SEAL-CoC enabled WSL2 features. The experiment resumes after sign-in."
            Stop-Transcript | Out-Null
            exit 100
        }
    }

    Set-Progress 'WSL' 'Updating/checking WSL2 runtime'
    & wsl.exe --update 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Warning 'Normal WSL update failed; trying --web-download.'
        & wsl.exe --update --web-download 2>&1 | Out-Host
    }
    & wsl.exe --set-default-version 2 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Could not set WSL default version to 2. Check virtualization/WSL installation.' }

    $Distro = Resolve-UbuntuDistro $PreferredDistro
    Set-Progress 'UBUNTU' "Using distro $Distro; initializing as root"
    & wsl.exe -d $Distro -u root -- bash -lc 'echo WSL_READY; uname -a; cat /etc/os-release | head -n 4' 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Save-WSLDiagnostics $Distro
        throw "Ubuntu '$Distro' is registered but cannot start. Check virtualization and wsl_diagnostics.txt."
    }

    Ensure-DistroWSL2 $Distro
    & wsl.exe --set-default $Distro 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { Write-Warning "Could not set '$Distro' as the default distro; this is non-fatal." }

    Set-Progress 'UBUNTU' 'Enabling systemd and restarting the distro'
    & wsl.exe -d $Distro -u root -- bash -lc "printf '[boot]\nsystemd=true\n' > /etc/wsl.conf" 2>&1 | Out-Host
    & wsl.exe --terminate $Distro 2>$null | Out-Null
    Start-Sleep -Seconds 3
    & wsl.exe -d $Distro -u root -- bash -lc 'echo WSL_READY_AFTER_SYSTEMD; ps -p 1 -o comm=' 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "'$Distro' failed after enabling systemd." }
    Save-WSLDiagnostics $Distro

    Set-Progress 'COPY' 'Copying bundle from Windows into native WSL filesystem'
    $wslRoot = Convert-WindowsPathToWSL $Root $Distro
    if (-not $wslRoot) { throw 'Could not translate the Windows project path to a WSL path.' }

    # Avoid bash positional parameters and `cp -a` for Windows->WSL copy.
    # On some WSL/PowerShell combinations a missing $1 made cp read `/.`, and
    # archival copy tries to preserve hard-link/reparse metadata across NTFS and
    # ext4. Pass argv directly to wsl.exe and use a non-archival recursive copy.
    $sourceDot = "$wslRoot/."
    & wsl.exe -d $Distro -u root -- test -f "$wslRoot/README.md" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Mapped source '$wslRoot' is not the SEAL-CoC bundle (README.md not found)."
    }
    & wsl.exe -d $Distro -u root -- rm -rf /root/seal-coc 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Could not clear /root/seal-coc in WSL.' }
    & wsl.exe -d $Distro -u root -- mkdir -p /root/seal-coc 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Could not create /root/seal-coc in WSL.' }
    & wsl.exe -d $Distro -u root -- cp -R --no-preserve=mode,ownership,timestamps,links -- $sourceDot /root/seal-coc/ 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Could not copy the experiment bundle into WSL from '$wslRoot'.  uses direct argv + non-archival copy to avoid WSL hard-link/reparse-point issues."
    }
    # Never reuse stale Windows-side benchmark output.
    & wsl.exe -d $Distro -u root -- rm -rf /root/seal-coc/results 2>$null | Out-Null
    & wsl.exe -d $Distro -u root -- mkdir -p /root/seal-coc/results 2>$null | Out-Null

    Set-Progress 'LINUX' 'Starting Docker/Fabric/Groth16/EVM experiment pipeline'
    & wsl.exe -d $Distro -u root -- chmod +x /root/seal-coc/scripts/linux/install_and_run.sh /root/seal-coc/scripts/linux/run_fabric.sh /root/seal-coc/scripts/linux/run_snark.sh /root/seal-coc/scripts/linux/run_evm.sh /root/seal-coc/scripts/linux/capture_environment.sh 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Could not mark Linux runner scripts executable.' }
    & wsl.exe -d $Distro -u root -- env "SEAL_WINDOWS_RESULTS=$wslRoot/results" bash /root/seal-coc/scripts/linux/install_and_run.sh 2>&1 | Out-Host
    $linuxCode = $LASTEXITCODE
    if ($linuxCode -ne 0) {
        # Best-effort copy even on failure so diagnostics are available on Windows.
        & wsl.exe -d $Distro -u root -- mkdir -p "$wslRoot/results" 2>$null | Out-Null
        & wsl.exe -d $Distro -u root -- cp -R --no-preserve=mode,ownership,timestamps,links -- /root/seal-coc/results/. "$wslRoot/results/" 2>$null | Out-Null
        throw "Linux experiment pipeline exited with code $linuxCode. See results\logs and results\progress.txt."
    }

    Set-Progress 'COPY' 'Copying final results back to Windows'
    & wsl.exe -d $Distro -u root -- mkdir -p "$wslRoot/results" 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Windows results directory through WSL.' }
    & wsl.exe -d $Distro -u root -- cp -R --no-preserve=mode,ownership,timestamps,links -- /root/seal-coc/results/. "$wslRoot/results/" 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Pipeline completed, but final result copy to Windows failed.' }

    Clear-OldResume
    Set-Progress 'DONE' "SUCCESS. Results are in $Root\results"
    Stop-Transcript | Out-Null
    exit 0
} catch {
    Clear-OldResume
    Set-Progress 'FAILED' $_.Exception.Message
    Write-Host "`nFATAL: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray
    Write-Host "`nRun CHECK_STATUS.cmd. Diagnostics: $Log and $(Join-Path $Root 'wsl_diagnostics.txt')" -ForegroundColor Yellow
    try { Stop-Transcript | Out-Null } catch {}
    exit 1
}
