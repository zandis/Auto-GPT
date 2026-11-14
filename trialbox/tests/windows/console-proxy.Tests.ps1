# NEW-WIN-10 (D-613, owner ruling D-503): deploy/windows/console-proxy.ps1 keeps the console's forwarding rule on
# Windows 10 pointed at WSL2's address, which changes at every start of WSL2.
# What this proves: which address is taken, how netsh's table is read in any display language, that the rule is
# changed only when it points elsewhere. What it cannot prove: netsh, wsl.exe or the Task Scheduler on Windows (P-0).

BeforeAll {
  $script:Root = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
  . (Join-Path $script:Root "deploy/windows/console-proxy.ps1") -LoadOnly
}

Describe "console-proxy.ps1" {
  BeforeEach {
    $script:P = @{ Wsl = "172.28.14.5 "; Table = @(); Netsh = New-Object System.Collections.ArrayList; NetshExit = 0 }
    Mock Get-TbWslAddressText { return [string]$script:P.Wsl }
    Mock Get-TbProxyTable { return $script:P.Table }
    Mock Invoke-TbNetsh { [void]$script:P.Netsh.Add(($Arguments -join " ")); return [int]$script:P.NetshExit }
  }

  It "takes WSL2's first IPv4 address, never a loopback, link-local or IPv6 one" {
    Select-TbWslAddress "172.28.14.5 fd00::5 " | Should -Be "172.28.14.5"
    Select-TbWslAddress "127.0.0.1 169.254.3.4 10.255.255.254 172.20.1.9" | Should -Be "10.255.255.254"
    Select-TbWslAddress "fe80::1 ::1" | Should -BeNullOrEmpty
    Select-TbWslAddress "" | Should -BeNullOrEmpty
    Select-TbWslAddress "999.1.1.1 172.20.1.9" | Should -Be "172.20.1.9"
  }

  It "reads netsh's table by its figures, whatever language its headings are in" {
    $table = @("", "Lauschen an IPv4:             Verbinden mit IPv4:", "", "Adresse         Port        Adresse         Port",
      "--------------- ----------  --------------- ----------", "0.0.0.0         443         172.28.1.7      443",
      "0.0.0.0         8080        10.0.0.2        80")
    Get-TbProxyTarget $table 443 | Should -Be "172.28.1.7"
    Get-TbProxyTarget $table 8443 | Should -BeNullOrEmpty
    Get-TbProxyTarget @("192.168.1.10    443         172.28.1.7      443") 443 | Should -BeNullOrEmpty  # another listen address
  }

  It "adds the rule when there is none" {
    $r = Update-TbConsoleProxy -Distro "TrialBox" -Port 443
    $r.Status | Should -Be "added"
    $r.Address | Should -Be "172.28.14.5"
    $script:P.Netsh | Should -Be @("interface portproxy add v4tov4 listenport=443 listenaddress=0.0.0.0 connectport=443 connectaddress=172.28.14.5")
  }

  It "changes the rule only when WSL2's address has changed" {
    $script:P.Table = @("0.0.0.0         443         172.28.14.5     443")
    (Update-TbConsoleProxy -Distro "TrialBox" -Port 443).Status | Should -Be "kept"
    $script:P.Netsh.Count | Should -Be 0
    $script:P.Wsl = "172.28.99.3"
    $r = Update-TbConsoleProxy -Distro "TrialBox" -Port 443
    $r.Status | Should -Be "changed"
    $script:P.Netsh | Should -Be @("interface portproxy set v4tov4 listenport=443 listenaddress=0.0.0.0 connectport=443 connectaddress=172.28.99.3")
  }

  It "leaves the rule alone when WSL2 gives no address, and says so" {
    $script:P.Table = @("0.0.0.0         443         172.28.14.5     443")
    $script:P.Wsl = ""
    $r = Update-TbConsoleProxy -Distro "TrialBox" -Port 443
    $r.Status | Should -Be "no_address"
    $script:P.Netsh.Count | Should -Be 0
  }

  It "reports a rule netsh refused" {
    $script:P.NetshExit = 1
    (Update-TbConsoleProxy -Distro "TrialBox" -Port 443).Status | Should -Be "refused"
  }

  It "keeps its log short" {
    $log = Join-Path $TestDrive "console-proxy.log"
    1..250 | ForEach-Object { Write-TbProxyLog $log ("line {0}" -f $_) }
    $lines = @(Get-Content -LiteralPath $log)
    $lines.Count | Should -BeLessOrEqual 200
    $lines[-1] | Should -Match "line 250$"
  }
}
