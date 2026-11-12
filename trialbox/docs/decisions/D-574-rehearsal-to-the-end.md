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
  148 open licence flags with no budget. **The owner's ruling of 2026-11-12** (first relayed by the integrator,
  then given by the owner in the build session, which is what let the allow-list be edited): dated, reviewed
  entries scoped to the image, as for HAPI, and a licence budget; review on 2026-12-10; building Caddy ourselves
  only if upstream is silent then. Done: three entries and a budget of 148. The image passes the gates.
- **Authelia** (`authelia/authelia:4.39.28`, the newest tag): eight fixable findings in its Go binary, and no
  package database in the image, so Trivy reads no OS package and the gate refused the report as blind. **The
  owner's ruling of 2026-11-12**, the same way: dated entries scoped to the image, a licence budget, and one
  narrow rule; each entry must say why the finding is not reachable on a box, and one that cannot be argued goes
  back to the owner by name.

### The narrow rule: `os_packages_unreadable`

A new list in the allow-list. One entry names one third-party image repository (never one of ours, never a
pattern), with a reason and a review date like every entry. For that image only, a Trivy report may show no OS
packages. It must still show packages of some kind, its findings are gated as always, and when the report does
show OS packages the entry is refused as stale. Without an entry the gate refuses a report with no OS packages,
as before. The shipped list has one entry: `authelia/authelia`, review 2026-12-10.

### Authelia: what each entry rests on

How a box runs it (`deploy/docker-compose.identity.yml`, `deploy/identity/Caddyfile`, the configuration template):
profile `oidc` only; it listens in plain HTTP/1 on 9091 inside `trialbox-net`, with no published port and no
`server.tls`; Caddy ends TLS and proxies to it in HTTP/1.1; the only outbound connection the egress rules allow
it is LDAPS to the hospital's directory (Authelia's start-up time check, to a public time server, is blocked). What is in the binary of the pinned image was
read from its symbol table on 2026-11-12.

| Finding | Why it is not reachable on a box |
| --- | --- |
| GO-2026-5932, x/crypto | the advisory is for the `openpgp` package; it is not in the binary |
| CVE-2026-78661, x/net | the flaw is in the HTML parser; only the package's `init` is in the binary, no parser function |
| CVE-2026-78669, x/net | of this module the binary links only `idna` and the `init` of `html`; there is no `golang.org/x/net/http2` in it |
| CVE-2026-78669, stdlib | needs a malicious HTTP/2 peer: there is no HTTP/2 server in the binary (fasthttp, HTTP/1.1), and the HTTP/2 client runs only on an outbound HTTPS call, which the box neither configures nor lets out |
| CVE-2026-78667, stdlib | the flaw is in `net/http` file serving; neither it nor the `net/http` server is in the binary |
| CVE-2026-97031, stdlib | the flaw is in the TLS server handshake; Authelia accepts no TLS connection on a box |
| CVE-2026-97054, stdlib | the race is in the `net/http` server's response; that server is not in the binary |

**CVE-2026-111943 (crypto/x509) has no entry and goes back to the owner by name.** It adds a list of
intermediate certificates that are no longer trusted. Authelia's LDAPS client verifies the directory's certificate
with the image's 121 public roots plus the hospital's own, so the code runs. To use the flaw an attacker has to
sit between the box and the directory inside the hospital's network and hold a certificate issued under one of
those intermediates for the directory's name. That is narrow, but it is not "not reachable". Until the owner
rules, the gate fails on this one finding, and it should.

A way to make it unreachable, not built here because it changes what a site must supply: mount a CA file with
only the hospital's own CA over the image's root list, so that no public intermediate can chain to a trusted
root.

The licence budgets: Caddy 148, Authelia 88 (the amd64 counts; the `images` job confirms arm64).

### After the adversarial review (2026-11-12)

- The narrow rule was not narrow enough: `image: authelia` would also have matched `someone/authelia`. An entry
  must now be, by its full name, a third-party image of `deploy/images.lock`, in ASCII, and it matches that one
  repository in any registry and no longer path that ends the same way.
- "Packages of some kind" let a report through whose only content was not a package scan. The report must show
  language packages (the image's binary).
- Two of the reasons rest on the site's configuration file and not on the binary: no `server.tls` (CVE-2026-97031)
  and no outbound HTTPS call (CVE-2026-78669 in the standard library). The TLS server and the HTTP/2 client are
  in the binary. The reasons say "on the box" and are true for the template; nothing yet refuses a site file that
  turns either on. Open, not built here: a check of the site's Authelia file.
- For Caddy the flawed code is live (the `net/http` server with a body limit, the HTML parser). Its entries are
  the owner's ruling on exposure: reachable on 443 from the hospital's inner network only.
