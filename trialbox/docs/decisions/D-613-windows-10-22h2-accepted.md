# D-613 Windows 10 22H2 is accepted; its console is forwarded to WSL2 by a port-proxy rule

- **Task:** NEW-WIN-10 (lane W), first in the lane on the owner's ruling D-503 of 2026-11-14 (typed in the
  integrator's session): "accommodate the sites' real machines, do not demand Windows 11"
- **PR:** this branch (`agent/NEW-WIN-10-windows-10`)
- **Date:** 2026-11-14
- **Status:** accepted. Nothing in it has run on Windows: the proof is the P-0 sheet's Part 9 (lines 71 to 83) on
  the owner's own PC, Windows 10 Pro 22H2, build 19045, an RTX 3080
- **Owner decisions:** D-503 (this card), D-494 (the workstation is also a desktop), OD-10
- **Updates:** D-600 (the Windows editions and build the installer takes) and D-604 (the console on the site's
  network: one form more)

## Context

D-600 took Windows 11 only, and D-604 raised the floor to Windows 11 22H2 (build 22621) because the console is
served with WSL2's mirrored networking, which only Windows 11 22H2 and later have. The owner's PC, and by his
account most hospital PCs, run Windows 10 Pro 22H2 (build 19045) with WSL2 already on. Requiring Windows 11 would
send every such site to an operating-system upgrade before TrialBox.

## Decision

1. **The installer takes Windows 10 22H2 (build 19045) and Windows 11**, as Pro, Pro for Workstations,
   Enterprise or Education (`-MinWindowsBuild` 19045). Home is still refused: it has no BitLocker. Both pre-flight
   checks take the same floor. Everything else is as it was: BitLocker, the boot task, the Windows Update window,
   the shutdown right and the key probe use what Windows 10 Pro has.
2. **The network form follows the build.** Windows 11 22H2 and later (build 22621 and up) keep mirrored networking
   and the Hyper-V firewall rule of D-604, unchanged. Every earlier build (Windows 10 22H2; also Windows 11 21H2)
   takes the form below; `wsl2_policy.py` and the installer name the same build.
3. **On a build without mirrored networking**, WSL2 sits behind an address of its own that changes at every start
   of WSL2. So:
   - one rule of Windows' port proxy (`netsh interface portproxy`, v4 to v4) passes port 443 from every address of
     the PC to WSL2's address (eth0's, read with `ip`; WSL's DNS-tunnel address and docker's bridges are never
     taken), and nothing else. A rule someone else made for port 443 on one address is left alone and the step
     stops; Windows' IP Helper service, which serves the port proxy, is started when it is only stopped, and the
     step stops when the site has switched it off (the site's IT decides);
   - `deploy/windows/console-proxy.ps1`, copied beside the installer's state (administrators only), reads WSL2's
     address and changes the rule only when it points elsewhere; it registers its own task,
     `TrialBox-Console-Proxy`, at startup and every `-ProxyEveryMinutes` (5) minutes for ten years, signed in or not
     (S4U, highest rights: only an administrator changes the port proxy), with the boot task's sign-in; a run is
     ended after two minutes, so a hung `wsl.exe` does not hold off the next ones;
   - one Windows Firewall rule, `TrialBox-Console`, lets port 443 in from the PC's own subnet on private and domain
     networks only. A rule of that name that is wider, on a public network or off is put right;
   - `.wslconfig` gets `localhostForwarding=false` and no `networkingMode` line: WSL2's own forwarding of
     `localhost` would take port 443 before the port proxy, and the port proxy also answers on `localhost`. An
     account's own `.wslconfig` is kept as before; the installer says when it lacks `swap=0` or
     `localhostForwarding=false`.
   The installer runs the script once at step 13 and stops when WSL2 gives no address or netsh refuses the rule; a
   finished install refreshes the rule, the task and the firewall rule at every start, quietly.
   On a PC upgraded to a Windows with mirrored networking, the installer's next run removes the task, the row and
   the Windows Firewall rule (they would hold port 443 against WSL2's own), and the host check fails a box where
   they are left.
4. **The host check** reads the build, the port-proxy row, the task and the IP Helper service (`host_facts.ps1`,
   still read-only) and, on a build without mirrored networking, fails a box whose forwarding is missing or whose
   IP Helper service is not running (a WARN in DEV and TEST).
5. **Windows 10's end of support is a site risk, not a refusal.** By Microsoft's published lifecycle (from
   memory, to be checked by the site), Windows 10's standard support ended on 2025-10-14; security updates continue
   only under Extended Security Updates (ESU), paid, for organisations. The host check warns on every Windows 10 box;
   the checklist says the site arranges ESU.

**What changes for the box.** Under the port proxy, the console sees every connection as coming from the PC's own
WSL-facing address, not from the client. The box's input firewall (D-408) is opened to the box's own network,
which `tools/box/plan.py` derives from the box's address; under NAT that address is in WSL2's own subnet, the same
subnet as the PC's WSL-facing address, so the forwarded connections are let in with no change to lane D's files (by
reading, not run: P-0 line 77). The site's network is then guarded by the Windows Firewall rule instead. The
console's record of who did what is by the signed-in person and is not affected; a client's network address is not
in the console's logs on this form.

**Not chosen.** WSL2's `localhost` forwarding with a rule for the PC's LAN address: the LAN address changes with
DHCP, which the task would have to follow too, and `localhost` forwarding is documented as best effort. A
Windows service of our own: more to install and to keep. If P-0 line 73 or 78 shows the port proxy does not serve
WSL2 as documented, that alternative is the next card.

**Known limit, kept.** The forwarding script takes the address WSL2's eth0 reports, so root inside WSL2 could point
the PC's port 443 at another host. Root inside WSL2 already owns the console itself, so this adds little; a check
that the address is inside the `vEthernet (WSL...)` adapter's subnet depends on an adapter name nothing here has
seen, and P-0 line 83 records it for a later card.

**Reuse check.** Windows' own port proxy, Windows Firewall and Task Scheduler cover it; one small script of ours
keeps the rule pointed. Nothing is added to the media but that script.

## What is proven here, and what is not

Proven here: the installer's logic for both builds with every Windows command behind a seam (Pester on PowerShell 7,
147 tests with the forwarding script's: Windows 10 Pro 22H2 to the end; Home and 19044 refused; the firewall rule
written, kept on a second run and put right when wider; the task registered again when deleted or disabled; no
address, a refused rule and another rule on the port stop the step; the IP Helper service started when stopped and
the step stopped when it is switched off; after the restart, the forwarding script found in the installer's own
copy; an account's own `.wslconfig` reported; the forwarding removed after an upgrade to mirrored networking;
Windows 11 unchanged; Windows 11 21H2 on the proxy form). The forwarding script's logic: which address, netsh's
table in any language, a change only when needed, a conflicting rule refused, its log kept short. The host check's
lines; both pre-flight checks' floor.

Not proven by a run here: the task's definition. Its registration (`Register-TbConsoleProxyTask`) and the runs are
behind seams; a test reads its text for S4U, highest rights, the two-minute limit and the ten-year repetition, not
what Windows makes of them. All of the following is on the P-0 sheet (Part 9): that `netsh interface portproxy`
passes the console to WSL2 on Windows 10 22H2 and that the IP Helper service listens for it; that the task runs at
startup and every five minutes with nobody signed in, with the limits written (line 82); that the rule follows WSL2
after `wsl --shutdown`; that eth0's address is the one Windows reaches; that `localhostForwarding=false` leaves port
443 free for the port proxy; that a PC on a network Windows calls Public is closed (expected) and on Private open;
anything about Windows 11 21H2 or an upgraded PC.

## Consequences

- P-0 can run on the owner's PC (Windows 10 Pro 22H2), with `-DataDrive G:` (G:, H: and I: have about 2 TB free).
- `docs/handover/P-0-BUILD-THE-MEDIA.md`, the P-0 sheet (Part 9), the checklist and `OFFLINE-MEDIA.md` say so.
