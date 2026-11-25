@echo off
setlocal
cd /d "%~dp0"
title SEAL-CoC Final Validation
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\RunFinalValidation.ps1"
set RC=%ERRORLEVEL%
if not "%RC%"=="0" (
  echo.
  echo Final validation failed with exit code %RC%.
  echo Check results\progress.txt and results\logs.
  pause
  exit /b %RC%
)
echo.
echo Final validation completed. Open results\final_report\SUBMISSION_READINESS.md
pause
