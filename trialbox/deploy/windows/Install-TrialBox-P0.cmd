@echo off
rem TrialBox P-0: start the installer for P-0 on this PC, as administrator (NEW-WIN-12, D-615; owner ruling D-510).
rem Double-click this file on the offline media. It starts windows\box-install.ps1 -P0 in an administrator window;
rem the choices of this P-0 (a rehearsal, BitLocker) are the media's own, in windows\p0.json.
rem The path goes through a variable, so a space, an apostrophe or an ampersand in it is only text.
set "TB_INSTALL_PS1=%~dp0windows\box-install.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "try { Start-Process powershell.exe -Verb RunAs -ErrorAction Stop -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -NoExit -File ' + [char]34 + $env:TB_INSTALL_PS1 + [char]34 + ' -P0') } catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 pause
