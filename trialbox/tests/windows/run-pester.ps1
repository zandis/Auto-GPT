# NEW-WIN-1: parse every PowerShell file of deploy/windows and run the Pester tests of tests/windows.
#   pwsh -NoProfile -File tests/windows/run-pester.ps1
# PowerShell 7 on Linux (the CI job `powershell`); Pester 5 and PSScriptAnalyzer. Exit 1 on a parse error or a failed test.
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$failed = 0
foreach ($f in Get-ChildItem -LiteralPath (Join-Path $root "deploy/windows") -Filter *.ps1) {
  $tokens = $null; $errors = $null
  [void][System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$tokens, [ref]$errors)
  if ($errors.Count -gt 0) {
    $failed++
    foreach ($e in $errors) { Write-Output ("PARSE {0}:{1}: {2}" -f $f.Name, $e.Extent.StartLineNumber, $e.Message) }
  } else { Write-Output ("parsed {0}" -f $f.Name) }
}
# Windows PowerShell 5.1 is what the site's workstation runs: no syntax newer than 5.1, and no analyzer error
Import-Module PSScriptAnalyzer
$rules = @{ Rules = @{ PSUseCompatibleSyntax = @{ Enable = $true; TargetVersions = @("5.1") } } }
foreach ($d in @(Invoke-ScriptAnalyzer -Path (Join-Path $root "deploy/windows") -Recurse -Settings $rules |
      Where-Object { $_.Severity -in @("Error", "ParseError") -or $_.RuleName -eq "PSUseCompatibleSyntax" })) {
  $failed++
  Write-Output ("ANALYZER {0}:{1}: {2}: {3}" -f $d.ScriptName, $d.Line, $d.RuleName, $d.Message)
}
Import-Module Pester -MinimumVersion 5.3.0
$cfg = New-PesterConfiguration
$cfg.Run.Path = $PSScriptRoot
$cfg.Run.PassThru = $true
$cfg.Output.Verbosity = "Detailed"
$result = Invoke-Pester -Configuration $cfg
if ($failed -gt 0 -or $result.FailedCount -gt 0 -or $result.TotalCount -eq 0) { exit 1 }
exit 0
