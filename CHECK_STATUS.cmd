@echo off
setlocal
cd /d "%~dp0"
title SEAL-CoC Status

echo ===================== WSL STATUS =====================
wsl.exe --status 2>&1
echo.
wsl.exe -l -v 2>&1
echo.
echo =================== PIPELINE STATUS ==================
if exist "results\progress.txt" (
  type "results\progress.txt"
) else (
  echo No results\progress.txt yet.
  echo This normally means the Linux experiment pipeline has not started.
)
echo.
echo ===================== LAST LOG =======================
if exist "windows_bootstrap.log" (
  powershell.exe -NoProfile -Command "Get-Content -Path '%~dp0windows_bootstrap.log' -Tail 35"
) else (
  echo windows_bootstrap.log not found.
)
echo.
pause
