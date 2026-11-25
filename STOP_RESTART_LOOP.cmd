@echo off
shutdown /a >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\RunOnce" /v SEALCoCResume /f >nul 2>&1
echo SEAL-CoC pending reboot cancelled and stale auto-resume entry removed.
echo You can now run RUN_ALL.cmd from the current bundle.
pause
