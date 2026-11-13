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

1. **The container's root list is the hospital's directory CA** (`deploy/docker-compose.identity.yml`):
   `TB_LDAP_CA` (one PEM file: the CA that issued the domain controller's certificate, with its intermediates) is
   mounted read-only at `/run/tb-ldap-ca.pem`; `SSL_CERT_FILE` names that file and `SSL_CERT_DIR` a path nothing
   is ever mounted at. Go's `crypto/x509` on Linux reads `SSL_CERT_FILE` instead of its list of bundle files and
   `SSL_CERT_DIR` instead of its certificate folders (read in the Go 1.24 and 1.25 source here by the reviewer,
   and run with a small program): the system pool then holds the file's certificates and nothing else.
2. **The mount is the long form with `create_host_path: false`.** A file that is not there stops the start. The
   short form would have made a root-owned folder of that name on the host; the container's root "file" would be
   a folder, and the operator's later copy would land inside it.
3. **A box whose hospital sign-in is on does not start without a usable file.** `pre-start` (the release's own
   steps, run by the update and by `install.sh` before any service is put on the release) ends with doctor's
   check and stops on a FAIL with the reason; an update that meets it puts the box back. So a site that already
   runs the hospital sign-in is told before, not by a sign-in page that no longer works. Local accounts (TOTP)
   are not affected either way.
4. **Doctor, `ldap_ca`** (FAIL in VALIDATION and PRODUCTION, WARN elsewhere), only when the hospital sign-in is
   on: the setting is missing, is a bare name (compose reads that as a volume), cannot be read, holds no real
   certificate, holds a private key, or holds a certificate that is also one of the public roots the checking
   machine trusts. That last one reads the content, not the path: a copy of the host's bundle under another name,
   or a link to it, is refused; the hospital's own CA passes wherever the host keeps it. `check_host.sh` hands
   the file to the doctor's container as one quoted argument.
5. The runbook (section 12), the settings example and the example configuration name `TB_LDAP_CA`. Before this
   card none of them said how a hospital's private CA was to be trusted at all.

## What this does not close

- **The site's own Authelia file can still widen the trust or switch the check off**: `certificates_directory`
  adds roots (the acceptance overlay uses it for its test CA), and `tls.skip_verify: true` turns verification
  off. Doctor reads neither (D-574 lists that check as open). This card removes the public roots the image
  ships; it does not police the site's configuration.
- **With no file, "trusts nothing" is not proven for the pinned binary.** Unset, the root file is `/dev/null`:
  Go gives an empty pool with no error, and a binary built with a compiled-in root list
  (`x509roots/fallback`) would then use that list (run by the reviewer with a stand-in for the fallback). Whether
  the pinned Authelia binary has one was not checked. So the guarantee is point 3, not the empty file: a
  PRODUCTION or VALIDATION box with the sign-in on is not started without a usable file. A DEV or TEST box is
  only warned.
- **The mail notifier.** The example configuration offers an `smtp:` notifier. With these settings a STARTTLS
  connection to a relay whose certificate is not under the hospital's directory CA fails when a mail is sent.
  The egress rules allow Authelia no SMTP on a box as shipped, so nothing changes there; a site that opens it
  puts the relay's CA in the same file.

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

- **That Authelia 4.39 builds its LDAPS trust from the system pool** (plus `certificates_directory`). From
  memory, not read in its source or run: no docker daemon here and no copy of its source. The whole card rests on
  it. For whoever has a box (lane G): start the oidc profile with `TB_LDAP_CA` set to a CA that did NOT issue the
  directory's certificate and see the LDAPS bind refused ("certificate signed by unknown authority"); then with
  the right CA and see it accepted.
- Whether Authelia stops at start when its directory cannot be reached with a certificate it trusts (then an
  update without the file would fail at the wait and roll back) or starts and fails each sign-in. Point 3 makes
  the question moot on a PRODUCTION box.

## Consequences

- **A box that already runs the hospital sign-in must set `TB_LDAP_CA` before the update that brings this**;
  the update stops at its first steps otherwise, with the reason, and the box stays on its release.
- A site that turns the hospital sign-in on must supply the directory CA file. Before, a directory certificate
  from a public CA worked with no file; now it needs that CA's chain in the file.
- A hospital whose directory certificate is renewed under a new CA updates the file and starts Authelia again.
