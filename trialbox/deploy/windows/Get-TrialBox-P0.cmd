@echo off
rem TrialBox P-0: fetch the P-0 media onto a USB disk (NEW-WIN-13, D-616). The one file the owner downloads.
rem The release workflow (.github/workflows/trialbox-p0-media.yml) writes the release's address, the manifest's name
rem and the sha256 of get-p0-media.ps1 into the three marks below; the script is checked before it is run.
set "TB_BASE=@RELEASE_BASE@"
set "TB_MANIFEST=@MANIFEST@"
set "TB_SHA=@SCRIPT_SHA256@"
set "TB_PS1=%TEMP%\TrialBox-P0-get-p0-media.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference = 'Stop'; Invoke-WebRequest -UseBasicParsing -Uri ($env:TB_BASE + '/get-p0-media.ps1') -OutFile $env:TB_PS1; if ((Get-FileHash -Algorithm SHA256 -LiteralPath $env:TB_PS1).Hash.ToLower() -ne $env:TB_SHA) { Remove-Item -LiteralPath $env:TB_PS1; Write-Host 'get-p0-media.ps1 is not the one this release was made with; nothing was run.'; exit 1 }"
if errorlevel 1 goto end
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%TB_PS1%" -Base "%TB_BASE%" -Manifest "%TB_MANIFEST%"
:end
pause
