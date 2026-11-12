# D-574 The box rehearsal runs the real installer to its end

- **Task:** OPS-004b (the second part of OPS-004, TB-PLAN-07 v7.2 wave 1, lane D; D-570 names what it left)
- **PR:** this branch (`agent/OPS-004b-rehearsal-to-the-end`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-570 (the rehearsal run again: five stops fixed, two named), D-176 (every image a box runs comes
  from the bundle; none is pulled), T-012b (a pin is the registry's expected manifest; champion only through a
  qualification record), D-569 (the shipped record and the install's promotion), D-566
- **Read by:** lane G (what only a real card proves), every card that changes `deploy/install.sh`

## Context

After D-570 the real `install.sh` runs inside the rehearsal's clean container up to the start of the stack. Two
things stood between it and "TrialBox is running": it asked for every pinned third-party image by its variable,
also for a model server that the rehearsal's stand-ins replace; and the rehearsal's placeholder weights are refused
by the rule that a pin is the registry's expected manifest.

## Decision

1. **The installer asks for the images its stack runs.** `tools/image_pins.py resolve` gets the rendered stack
   (`docker compose config --images` with the box's overrides). A pinned variable whose image no service runs is
   noted and not asked for. What the stack runs must still be on the box, by digest or by the bundle's pin, and the
   second check (every image of the rendered stack is on the box, nothing is pulled) is unchanged.
2. **The rehearsal's bundle carries what the box's stack runs**: the image list comes from the file set
   `install.sh` uses for the rehearsal's answers, with the stand-ins' override.

(The rest of this record is written as the rehearsal reaches each further stop.)

## Consequences

- A site that replaces a service through its compose override is not asked for the replaced service's image.
- No setting, no limit, no new store.

## The identity overlay was never gated (found 2026-11-12)

The rehearsal's bundle is the first one built the way `tools/make_bundle.sh` builds a real one: with the identity
overlay (Caddy, Authelia). The release gates stopped it at Caddy. The cause is older than the rehearsal: the
gates' image list (`SC_THIRD_PARTY` in the Makefile) was made from the box's compose file and the test overlay
only. Caddy and Authelia were in every bundle and in no gate record, so `bundle-check` could not have passed a
real release bundle.

- **Fixed here:** the list takes the identity overlay and the `oidc` profile too, with the same placeholder host
  name the bundle uses. `tests/unit/test_gate_image_list.py` holds the list to the bundle's files and profiles,
  and asks for a pin and a licence budget for every third-party image of a bundle.
- **Caddy** (`caddy:2.11.9-alpine`, the newest tag): three fixable findings in its Go binary on amd64 and arm64
  alike (GO-2026-5932 in x/crypto, CVE-2026-78661 in x/net, CVE-2026-97054 in the Go standard library 1.27.3) and
  148 open licence flags with no budget. The owner's ruling of 2026-11-12, relayed by the integrator: dated,
  reviewed allow-list entries scoped to the image, as for HAPI, and a licence budget; building Caddy ourselves
  only if upstream stays silent. **The entries are not in this branch**: the build session's permission layer
  refuses allow-list additions made on a relayed ruling. They are for the owner to add or to approve directly.
- **Authelia** (`authelia/authelia:4.39.28`, the newest tag): eight fixable findings in its Go binary, and no
  package database in the image, so Trivy reads no OS package and the gate refuses the report as blind. Not
  ruled yet; the choices went to the integrator on 2026-11-12.

Until both are settled the third test of `test_gate_image_list.py` fails and the `images` job fails on these two
images. That is the state of the gates, shown; nothing was skipped or waived to hide it.

### The Caddy entries as ruled, for the owner to add to `deploy/supply-chain-allowlist.yaml`

Under `vulnerabilities:`, three entries, each with `image: caddy`, `review_by: 2026-12-10` (or the next Caddy
release, whichever is first) and `owner: security owner (to assign)`:

| id | package | reason |
| --- | --- | --- |
| GO-2026-5932 | `golang-org/x/crypto` | Go module inside the upstream Caddy binary, fixed in x/crypto 0.58.1 |
| CVE-2026-78661 | `golang-org/x/net` | Go module inside the upstream Caddy binary, fixed in x/net 0.62.0 |
| CVE-2026-97054 | `stdlib` | Go standard library 1.27.3 inside the upstream Caddy binary, fixed in 1.27.4 |

Each reason ends with: listener on the hospital's inner network behind the box's egress rules; no fixed upstream
Caddy image exists (2.11.9 is the newest, checked 2026-11-12).

Under `budgets:`, one entry: `image: caddy`, `ecosystem: "*"`, `max: 148`, `review_by: 2027-02-01`, reason:
official Caddy image unmodified (Apache-2.0 project); the Go modules of its binary carry no licence data for Syft.
The count is the amd64 image's; the arm64 count is confirmed by the `images` job.
