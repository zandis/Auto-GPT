# D-722 Authelia trusts only the hospital's directory CA

- **Task:** AUTHELIA-CA (the owner's condition of 2026-11-13 on the entry for CVE-2026-111943, D-574)
- **PR:** this branch (`agent/AUTHELIA-CA-only-the-hospitals-directory-ca`), stacked on #381 (OPS-004b)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-574 (the login front against the gates), D-192 (the hospital account through Authelia)

## Context

Authelia's one outbound connection on a box is LDAPS to the hospital's directory. Its client verifies the
directory's certificate against the image's 121 public roots. CVE-2026-111943 (intermediates that `crypto/x509`
should no longer trust) is therefore reachable, narrowly: from inside the hospital's network, with a certificate
under such an intermediate. The owner allowed one dated entry on the condition that the real fix is built now and
removes the entry.

## Decision

1. **The container's whole root list is the hospital's directory CA** (`deploy/docker-compose.identity.yml`):
   `TB_LDAP_CA` (one PEM file: the CA that issued the domain controller's certificate, with its intermediates) is
   mounted read-only at `/run/tb-ldap-ca.pem`; `SSL_CERT_FILE` names that file and `SSL_CERT_DIR` a path nothing
   is ever mounted at. Go's `crypto/x509` on Linux reads `SSL_CERT_FILE` instead of the image's bundle and
   `SSL_CERT_DIR` instead of its certificate folders, so the system pool Authelia builds holds the hospital's
   certificates and nothing else: no public root, and no intermediate that could chain to one.
2. **Unset, it trusts nothing.** The mount's default is `/dev/null`: an empty root list. Every LDAPS handshake
   fails and no hospital account signs in. Closed, never back to the public roots.
3. **Doctor, `ldap_ca`** (FAIL in VALIDATION and PRODUCTION, WARN elsewhere), only when the hospital sign-in is
   on: the setting is missing, the file cannot be read, holds no certificate, holds a private key, or is the
   host's public root list (the one way to undo this with a setting). `check_host.sh` hands the file to the
   doctor's container.
4. Nothing else of Authelia needs a public root: it serves plain HTTP inside `trialbox-net`, the egress rules
   allow it LDAPS to the directory and nothing else, and its start-up time check is blocked (D-574).
5. The runbook (section 12), the settings example and the example configuration name `TB_LDAP_CA`. Before this
   card none of them said how a hospital's private CA was to be trusted at all.

## The allow-list entry: NOT removed here. Owner decision needed

The owner's condition was "when that lands, remove the entry". It cannot be done as written without breaking the
image gate: the scanner reads the Authelia binary, not how the box runs it, and goes on reporting
CVE-2026-111943 for the pinned image. With no entry the `images` gate fails on that finding, on every train.

So this card leaves `deploy/supply-chain-allowlist.yaml` as #381 has it (the owner's dated entry of
2026-11-13), and asks. Proposed: replace the owner's acceptance entry by a "Not reachable" entry of the same
kind as the other seven for this image (D-574), same review date, whose reason is the fact this card makes true:
"the container's root list is the hospital's directory CA only (D-722): no public root or intermediate can chain
to a trusted root". That is an allow-list edit other than the one the owner approved, so it waits for the
owner's yes.

## Not proven here

- **That Authelia in the pinned image honours the two variables.** Not run: no docker daemon in this session, and
  no Go toolchain. It rests on Go's documented behaviour (`crypto/x509`, Unix: `SSL_CERT_FILE` and
  `SSL_CERT_DIR` override the system locations) and on Authelia building its pool from the system pool. For
  whoever has a box (lane G): start the oidc profile with `TB_LDAP_CA` set to a CA that did NOT issue the
  directory's certificate and see the LDAPS bind refused ("certificate signed by unknown authority"); then with
  the right CA and see it accepted; then with `TB_LDAP_CA` unset and see it refused.
- If the image's Go were built with a root list compiled in (`x509roots/fallback`), the fallback is used only
  when the system pool is empty: with the hospital's file present it is not. With the file unset (the `/dev/null`
  default) a compiled-in list would be used, and point 2 would not hold. Not checked in the binary: the same
  test on a box says.

## Consequences

- A site that turns the hospital sign-in on must supply the directory CA file. Before, a directory certificate
  from a public CA worked with no file; now it needs that CA's chain in the file.
- A hospital whose directory certificate is renewed under a new CA updates the file and starts Authelia again.
