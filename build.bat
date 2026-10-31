@echo off
rem Builds the Monkey Viewer installer (MSI) and portable ZIP into .\release - see docs\BUILD.md
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1" %*
pause
