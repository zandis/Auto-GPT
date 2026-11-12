@echo off
rem TrialBox: start the installer for a Windows workstation as administrator (NEW-WIN-1, D-600).
rem Double-click this file on the offline media. It only starts windows\box-install.ps1 in an administrator window.
rem The path goes through a variable, so a space, an apostrophe or an ampersand in it is only text.
set "TB_INSTALL_PS1=%~dp0windows\box-install.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "try { Start-Process powershell.exe -Verb RunAs -ErrorAction Stop -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -NoExit -File ' + [char]34 + $env:TB_INSTALL_PS1 + [char]34) } catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 pause
