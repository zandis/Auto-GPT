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
    $script:P = @{ Wsl = "2: eth0    inet 172.28.14.5/20 brd 172.28.15.255 scope global eth0\       valid_lft forever preferred_lft forever"; Table = @(); Netsh = New-Object System.Collections.ArrayList; NetshExit = 0 }
    Mock Get-TbWslAddressText { return [string]$script:P.Wsl }
    Mock Get-TbProxyTable { return $script:P.Table }
    Mock Invoke-TbNetsh { [void]$script:P.Netsh.Add(($Arguments -join " ")); return [int]$script:P.NetshExit }
  }

  It "takes eth0's IPv4 address from ip's line, never a loopback, link-local or WSL's DNS-tunnel address" {
    Select-TbWslAddress "2: eth0    inet 172.28.14.5/20 brd 172.28.15.255 scope global eth0" | Should -Be "172.28.14.5"
    # WSL 2.x puts 10.255.255.254 on lo for its DNS tunnel; Windows cannot reach it (review finding 3)
    Select-TbWslAddress "inet 10.255.255.254/32 scope global lo inet 172.20.1.9/20 scope global eth0" | Should -Be "172.20.1.9"
    Select-TbWslAddress "inet 127.0.0.1/8 inet 169.254.3.4/16" | Should -BeNullOrEmpty
    Select-TbWslAddress "172.28.14.5 fd00::5" | Should -BeNullOrEmpty    # a bare address is not ip's line
    Select-TbWslAddress "" | Should -BeNullOrEmpty
    Select-TbWslAddress "inet 999.1.1.1/20 inet 172.20.1.9/20" | Should -Be "172.20.1.9"
  }

  It "reads netsh's table by its figures, whatever language its headings are in" {
    $table = @("", "Lauschen an IPv4:             Verbinden mit IPv4:", "", "Adresse         Port        Adresse         Port",
      "--------------- ----------  --------------- ----------", "0.0.0.0         443         172.28.1.7      443",
      "0.0.0.0         8080        10.0.0.2        80")
    $rows = @(Get-TbProxyRows $table)
    $rows.Count | Should -Be 2
    $rows[0].ListenAddress | Should -Be "0.0.0.0"; $rows[0].ListenPort | Should -Be 443
    $rows[0].ConnectAddress | Should -Be "172.28.1.7"; $rows[0].ConnectPort | Should -Be 443
    @(Get-TbProxyRows @("Adresse Port Adresse Port")).Count | Should -Be 0
  }

  It "refuses to add a second listener when another rule already takes the port on one address (review finding 8)" {
    $script:P.Table = @("192.168.1.10    443         172.28.1.7      443")
    $r = Update-TbConsoleProxy -Distro "TrialBox" -Port 443
    $r.Status | Should -Be "conflict"
    $script:P.Netsh.Count | Should -Be 0
  }

  It "re-points a row that has the right address but the wrong port" {
    $script:P.Table = @("0.0.0.0         443         172.28.14.5     8443")
    (Update-TbConsoleProxy -Distro "TrialBox" -Port 443).Status | Should -Be "changed"
    $script:P.Netsh.Count | Should -Be 1
  }

  It "defines its task with a short time limit and a repetition of its own length (review findings 2 and 9)" {
    $text = Get-Content -LiteralPath (Join-Path $script:Root "deploy/windows/console-proxy.ps1") -Raw
    $text | Should -Match "-ExecutionTimeLimit \(New-TimeSpan -Minutes 2\)"
    $text | Should -Match "-RepetitionDuration \(New-TimeSpan -Days 3650\)"
    $text | Should -Match "-LogonType S4U -RunLevel Highest"
    $text | Should -Match "-MultipleInstances IgnoreNew"
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
    $script:P.Wsl = "inet 172.28.99.3/20 scope global eth0"
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
