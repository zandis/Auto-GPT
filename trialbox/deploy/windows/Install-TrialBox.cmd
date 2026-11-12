@echo off
rem TrialBox: start the installer for a Windows workstation as administrator (NEW-WIN-1, D-600).
rem Double-click this file on the offline media. It only starts windows\box-install.ps1 in an administrator window.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell.exe -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -NoExit -File \"%~dp0windows\box-install.ps1\"'"
