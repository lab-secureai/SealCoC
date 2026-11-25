@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title SEAL-CoC - Continue Setup
fltmc >nul 2>&1
if errorlevel 1 (
  echo Requesting Administrator permission...
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b 0
)
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Bootstrap.ps1" -Mode Continue
set RC=%ERRORLEVEL%
if not "%RC%"=="0" (
  echo Setup stopped with exit code %RC%.
  echo Check windows_bootstrap.log and results\progress.txt.
  pause
  exit /b %RC%
)
echo SEAL-CoC setup completed.
pause
