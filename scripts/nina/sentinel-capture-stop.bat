@echo off
REM Point a NINA "External Script" sequence instruction at this file to
REM stop PFR Sentinel capture. See README.md in this folder.
REM Blocks until capture reaches the target state; a non-zero exit code
REM fails the sequence step so the problem is visible in NINA's log.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Invoke-SentinelCapture.ps1" -Command stop
exit /b %ERRORLEVEL%
