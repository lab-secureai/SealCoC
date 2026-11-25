@echo off
setlocal
cd /d "%~dp0"
title SEAL-CoC Paper Experiments
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\RunPaperExperiments.ps1"
set RC=%ERRORLEVEL%
if not "%RC%"=="0" (
  echo.
  echo Paper experiment suite failed with exit code %RC%.
  echo Check results\progress.txt and results\logs.
  pause
  exit /b %RC%
)
echo.
echo Paper experiment suite completed. Open results\paper_ready\
pause
