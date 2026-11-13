# D-629 The box's clinic range is the network of the interface its default route uses

- **Task:** BOX-LAN (from lane W's review of #437 by reading, through the integrator, 2026-11-13)
- **PR:** this branch (`agent/BOX-LAN-the-default-routes-network`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-466 (the box plan writes the host baseline from the detected hardware), T-634 (443 answers
  only `CLINIC_RANGES`)

## Context

The box plan writes `CLINIC_RANGES` in `deploy/site/hardening.conf`: the networks that may reach the console on
port 443. It took the first global IPv4 address `ip` listed that was not on a container bridge, and read no
IPv6. Three ways that is the wrong network:

- under WSL2 mirrored networking, WSL adds a loopback address as a /32 on a global-scope interface: the range
  becomes one address, and 443 answers nobody;
- a VPN adapter listed first: 443 answers the VPN's network and not the clinic's;
- a clinic on IPv6 is not read at all.

This decides who reaches the console, so a wrong guess must not be written as if it were known.

## Decision

1. The range is the network of **the interface the default route uses**: its IPv4 network and, when it has a
   global IPv6 address, that network too (`CLINIC_RANGES` takes both). The routes are read for both families;
   the lowest metric wins.
2. Never taken as the clinic's network: a loopback address or interface, a host address (/32, /128), a
   link-local address, a container bridge, and a tunnel (`tun`, `tap`, `wg`, `ppp`, `tailscale`, `zt`, or a
   point-to-point link). When the default route goes through one of these, the next route is looked at.
3. With no default route to go by, the range is taken only when exactly one interface is left that could be the
   clinic's. Several, or none: the plan writes no network (the loopback range, as before when nothing was
   found) and says so; the owner or IT names the range. A box with no gateway and one network card is the
   common hospital case and is still found.
4. `Hardware.lan` stays one string; it may now hold two ranges separated by a space.

## Consequences

- A box behind a full-tunnel VPN, or with two clinic networks and no default route, is not guessed: its console
  answers only the box itself until the range is named.
- For lane W and lane G: on WSL2 mirrored networking and on a box with a VPN up, `python3 -m tools.box detect`
  prints the clinic's network or nothing, never the loopback /32 or the VPN's.
