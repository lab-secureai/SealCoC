@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title SEAL-CoC One-Click Experiment 

if /I "%~1"=="ELEVATED" goto :elevated

REM Self-elevate the whole launcher. The old v2 elevated only PowerShell and the
REM original CMD could misleadingly print "Completed" while setup was detached.
fltmc >nul 2>&1
if errorlevel 1 (
  echo Requesting Administrator permission...
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs -ArgumentList 'ELEVATED'"
  exit /b 0
)

goto :elevated

:elevated
shutdown /a >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\RunOnce" /v SEALCoCResume /f >nul 2>&1

echo ================================================================
echo  SEAL-CoC Experiments
echo  WSL/Ubuntu - Docker - Fabric - Groth16 - EVM - Paper results
echo ================================================================
echo.
echo This window MUST stay open while the experiment is running.
echo Live status is also written to results\progress.txt.
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Bootstrap.ps1" -Mode All
set EXITCODE=%ERRORLEVEL%

echo.
if "%EXITCODE%"=="100" (
  echo Windows features need one reboot. Resume has been registered.
  echo If it does not resume automatically after login, double-click CONTINUE_AFTER_WSL.cmd.
  pause
  exit /b 0
)
if not "%EXITCODE%"=="0" (
  echo SEAL-CoC stopped with exit code %EXITCODE%.
  echo Run CHECK_STATUS.cmd and inspect windows_bootstrap.log.
  pause
  exit /b %EXITCODE%
)

echo ================================================================
echo SUCCESS - experiment pipeline completed.
echo Results: %~dp0results
echo ================================================================
start "" explorer.exe "%~dp0results"
pause
