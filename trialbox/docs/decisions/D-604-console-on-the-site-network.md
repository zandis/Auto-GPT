# D-604 The console on the site's network: mirrored networking and one firewall rule

- **Task:** NEW-WIN-4 (`docs/plan/33-plan-v7.md` section 2.3; lane W; wave 3)
- **PR:** this branch (`agent/NEW-WIN-4-console-on-the-network`), stacked on NEW-WIN-8 part 1 (D-603)
- **Date:** 2026-11-13
- **Status:** accepted for the form chosen and the installer's logic. Nothing in it has run on Windows: the proof
  is test P-14 on the reference workstation, rehearsed at P-0 (lines 37 to 45)
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
   - the box sees the site's real network. Under address translation `tools/box detect` reads WSL2's private
     subnet as "the box's network", and the input firewall inside WSL2 (D-408) would be opened to the wrong one;
   - nothing must be refreshed after a restart: no address to look up, no second moving part in the boot task.
2. **The port proxy is not built.** It is compared by hand at P-14 (the sheet gives the three commands). If
   mirrored networking fails P-14, the proxy becomes a card of its own; building both now would be work on a
   form that may never ship.
3. **One rule lets the console in, and only from the site's own network.** Under mirrored networking WSL2 sits
   behind Windows' Hyper-V firewall. The installer keeps its default for WSL at "block inbound" and adds one rule,
   `TrialBox-Console`: TCP, the console's port, inbound, from the workstation's own subnet (`LocalSubnet`). The
   port is the one port the stack publishes (443; a test holds the installer's figure and the compose file
   together). A rule of that name that is there is kept. The installer changes no other firewall setting and
   holds no command that turns a firewall off.
4. **The installer checks the mode before it opens anything.** Step 13 `network` asks WSL2 for its networking
   mode; anything but `mirrored` stops it (an old WSL, or the account's own `.wslconfig` that was kept at step 6),
   with what to add. The Windows build floor moves from 22000 to 22621 (Windows 11 22H2, the first with mirrored
   networking); D-600 point 12's figure is superseded by this one.
5. **The egress table must be seen loaded.** The install is not counted as finished until `wsl-setup.sh
   egress-check` finds `trialbox-egress.service` active and the nftables table `inet trialbox_egress` loaded
   inside WSL2. That proves "loaded", not "holds": that a container has no way out, and that only the console's
   port answers from another PC, are P-14's two scans (outward and inward). If the table cannot load or does not
   hold under mirrored networking, its rule moves to Windows Firewall, as the plan says; that is not built here.
6. **The TLS name and the network sheet follow without a change here.** WSL2's host name is the workstation's
   name, so `tools/box plan` already proposes it as the TLS name. The site's network sheet says one inbound
   port; under this form that port is on the workstation's own address. Its wording for Windows is NEW-WIN-9's.

## What is proven here, and what is not

Proven (Pester, every Windows command replaced): the step's order (before the Linux installer); the rule's name
and port; one rule, kept on a second run; the stop when WSL2 is not mirrored, with nothing opened; the unfinished
state while the egress table is not loaded. Proven (pytest): the two new steps of `wsl-setup.sh` on stubs; the
port equals the stack's one published port; the rule's text (inbound, the local subnet, block by default).

Not proven, by Microsoft's documentation and not run (Microsoft Learn: "Accessing network applications with WSL",
mirrored mode; "Configure Hyper-V firewall"; `New-NetFirewallHyperVRule`): that Docker inside WSL2 publishes a
port on the workstation's address under mirrored networking; that the Hyper-V firewall, not the ordinary Windows
Firewall, decides inbound traffic to WSL2 in that mode, and that `LocalSubnet` means the workstation's subnet
there; that `wslinfo --networking-mode` answers `mirrored`; that nftables in the WSL2 kernel loads the egress
table and that it still filters container traffic under mirrored networking; that the name resolves from another
PC. P-0 lines 37 to 45; P-14 on the reference workstation, after a restart.
