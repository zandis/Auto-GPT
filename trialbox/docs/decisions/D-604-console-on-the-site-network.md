# D-604 The console on the site's network: mirrored networking and one firewall rule

- **Task:** NEW-WIN-4 (`docs/plan/33-plan-v7.md` section 2.3; lane W; wave 3)
- **PR:** this branch (`agent/NEW-WIN-4-console-on-the-network`), stacked on NEW-WIN-8 part 1 (D-603)
- **Date:** 2026-11-13
- **Status:** accepted for the form chosen and the installer's logic. Nothing in it has run on Windows: the proof
  is test P-14 on the reference workstation, rehearsed at P-0 (lines 37 to 44)
- **Owner decisions:** D-494 (the workstation is also a desktop; the console is served to the site's own network),
  OD-15 (the default is "inside only")
- **Builds on:** D-600 (the installer), D-601 (`.wslconfig`), D-377 (the egress table loaded before Docker), D-176
  (the host input chain), D-408 (the input firewall open to the box's own network)

## Context

WSL2's default networking puts the distribution behind an address translation: it has an address of its own that
changes at every start, and only the workstation itself reaches it. The plan names two ways out: WSL2's mirrored
networking with a firewall rule for the console port, or a port proxy on Windows that the boot task refreshes; the
one that passes P-14 is kept. Nobody has run the egress table of D-377 under either.

## Decision

1. **The form built is mirrored networking.** `.wslconfig` gets `networkingMode=mirrored`: WSL2 uses the
   workstation's own network addresses. Reasons, before any measurement:
   - the console answers on the workstation's own name and address, which the TLS name and the network sheet
     already assume;
   - the box can see the site's real network. Under address translation `tools/box detect` reads WSL2's private
     subnet as "the box's network", and the input firewall inside WSL2 (D-408) would be opened to the wrong one.
     Under mirrored networking the right network is there to be read, but `detect` (lane D's) takes the first
     address it finds, which may be a loopback address WSL adds or a VPN adapter's: that is a change for lane D,
     named to the integrator. Until then the installer checks it after the install (`wsl-setup.sh lan-check`:
     the box's `CLINIC_RANGES` must hold the address of the interface the default route uses) and warns in plain
     words when the console would not answer from other computers;
   - nothing must be refreshed after a restart: no address to look up, no second moving part in the boot task.
2. **The port proxy is not built, and not rehearsed by hand.** A by-hand comparison was drafted for the P-0
   sheet and withdrawn after review: it stopped the box, left a listener on every adapter while in place, and the
   proxied traffic would have been dropped by the box's own firewall for an unrelated reason, so it compared
   nothing fairly. If mirrored networking fails P-14, the proxy becomes a card of its own with its own test;
   building both now would be work on a form that may never ship.
3. **One rule lets the console in, and only from the site's own network.** Under mirrored networking WSL2 sits
   behind Windows' Hyper-V firewall. The installer keeps its default for WSL at "block inbound" and adds one rule,
   `TrialBox-Console`: TCP, the console's port, inbound, from the workstation's own subnet (`LocalSubnet`). The
   port is the one port the stack publishes (443; a test holds the installer's figure and the compose file
   together). A rule of that name is the installer's: one that is exactly right is kept; one that is wider, for
   another port or switched off is set back and the window says so. "Block inbound" is a setting for every WSL
   distribution on the workstation, every account's: when it was open the installer closes it, logs what it was,
   and says so. The installer changes no other firewall setting and holds no command that turns a firewall off.
   `LocalSubnet` is every network the workstation is directly on (a second adapter and a VPN adapter too), and a
   site whose staff sit on another, routed network is not admitted: a setting for that is a later card. Traffic
   from the workstation's own desktop to the console (localhost) is not governed by this rule and is wanted: staff
   use the console at the workstation. No other port of the stack is published, on localhost either.
   A finished install made before this card gets the rule too: its next start writes the new `.wslconfig`, asks
   for one restart of Windows, and the start after that adds the rule.
4. **The installer checks the mode before it opens anything.** Step 13 `network` asks WSL2 for its networking
   mode; anything but `mirrored` stops it (WSL2 was already running when `.wslconfig` was written, an old WSL, or
   the account's own `.wslconfig` that was kept at step 6): the message says to restart Windows first, and what
   to add to a kept file. A Windows 11 older than the floor is told the build it needs. The Windows build floor moves from 22000 to 22621 (Windows 11 22H2, the first with mirrored
   networking); D-600 point 12's figure is superseded by this one.
5. **The egress table must be seen loaded, and seen to act.** The install is not counted as finished until
   `wsl-setup.sh egress-check` finds `trialbox-egress.service` active and the nftables table `inet
   trialbox_egress` loaded inside WSL2. Then, with the stack up, `wsl-setup.sh egress-proof` lets a container on
   the egress network (one that has a route out; the table is what stops it) try an address that is nobody's
   (192.0.2.1) and reads the table's own counter of dropped packets. The counter rose: held. The connection
   succeeded: the table does not act, the install is not finished and the window says the box must not get real
   data. Neither: not proven, said as a warning (a refused connection alone proves nothing). That only the
   console's port answers from another PC is P-14's inward scan. If the table cannot load or does not
   hold under mirrored networking, its rule moves to Windows Firewall, as the plan says; that is not built here.
6. **The TLS name and the network sheet.** WSL2's host name is the workstation's name, so `tools/box plan`
   already proposes it as the TLS name. Whether the name opens the console from another PC is not settled: a
   Windows name often resolves to an IPv6 address first, and the box's inner firewall admits IPv4 ranges only
   (`detect` reads IPv4). P-0 line 39 records which of the name and the address works; IPv6 is with lane D's
   `detect` change. The site's network sheet says one inbound
   port; under this form that port is on the workstation's own address. Its wording for Windows is NEW-WIN-9's.

## What is proven here, and what is not

Proven (Pester, the firewall's cmdlets replaced, the installer's own decisions run): the step's order (before the
Linux installer); the rule's name and port; one rule, kept on a second run; a wider, wrong-port or switched-off
rule set back; an open default closed and said; a finished install of before this card; the stop when WSL2 is not mirrored, with nothing opened; the unfinished
state while the egress table is not loaded. Proven (pytest): the two new steps of `wsl-setup.sh` on stubs; the
port equals the stack's one published port; the rule's text (inbound, the local subnet, block by default).

Not proven, by Microsoft's documentation and not run (Microsoft Learn: "Accessing network applications with WSL",
mirrored mode; "Configure Hyper-V firewall"; `New-NetFirewallHyperVRule`): that Docker inside WSL2 publishes a
port on the workstation's address under mirrored networking; that the Hyper-V firewall, not the ordinary Windows
Firewall, decides inbound traffic to WSL2 in that mode, and that `LocalSubnet` means the workstation's subnet
there, and what its loopback setting lets the workstation's own desktop reach; that `wslinfo --networking-mode`
answers `mirrored`; how DNS for the containers behaves under the egress table in this mode; that nftables in the WSL2 kernel loads the egress
table and that it still filters container traffic under mirrored networking; that the name resolves from another
PC. P-0 lines 37 to 44; P-14 on the reference workstation, after a restart.
