# D-1133 The session's links: the product's enrolment code, one private object, read once and deleted

- **Task:** lane H, card H-13 (SESSION-LINKS of D-1123 section 7)
- **PR:** this branch (`claude/lane-h-13-live-session`)
- **Date:** 2026-11-17
- **Status:** proposed
- **Builds on:** D-776 (a one-time link), D-719 (the enrolment code), D-423 (no secret in metadata), D-1120

## Decision

1. **The product's own code.** `56-session-accounts` opens each account in the console's own container:
   - DEV: `console.steps_roles.open_people` (D-877);
   - VALIDATION: `UserStore.open_by_code` (D-719).

   Each holder chooses their password at `/enrol`. An unused code expires after `tb-session-code-hours` (24, D-776).
2. **One private object, nowhere else.** The snippet's lines go to a root-only file on the VM. The VM then writes
   one text file and copies it to `$TB_BUCKET/session/<run id>/links-<stamp>.txt`, the only place a code is kept,
   and removes both files. The file holds:
   - one link a person: `https://<host>/enrol#u=<name>&c=<code>`. The code sits after `#`, so it is in no request
     to the box;
   - the boot id, the box's root certificate SHA-256 and the stop time in UTC;
   - "NOTHING FROM THIS SESSION IS EVIDENCE" and "public or synthetic text only";
   - the hosts line for the box's TLS name, when the box answers under a name.

   No code goes to the metadata, the serial port, a step log, `results.tgz` or `records/session.json`. A code not
   of the product's form (letters, digits, hyphens) stops the step before anything is written.
3. **Read once: `box-run.sh --links <run id>`.** It proves the door again (D-1130) and that the bucket is private,
   then prints the newest object once and deletes every links object of the run. It prints the boot id, the
   certificate's SHA-256 and the stop time as their own lines, for the owner to compare. A second read finds
   nothing, and new links need a new launch. The integrator gives the owner his line in the integrator's own
   session (the integrator's answer 5), never on a PR, in a comment or in a file.
4. **The address.** `TB_CONSOLE_PUBLIC_URL` is set to `https://<host>`: the box's own TLS name
   (`TB_TLS_HOSTNAME`), else the VM's external address. The links name the same host.
5. **The bucket** (the security review's finding 4). Before the launch and before `--links`, the bucket must hold:
   - no `allUsers` or `allAuthenticatedUsers` binding;
   - uniform bucket-level access, or public access prevention enforced;
   - versioning off.

   `--links` deletes with `--all-versions`. Two risks are bounded, not removed, and are questions for the
   integrator:
   - **Soft delete.** The hand-over says the bucket keeps deleted objects 7 days. A deleted links object stays
     restorable by the project's storage administrators for that long. `--links` prints the bucket's retention.
   - **A shared service account.** The VM writes the object as the Compute Engine default service account. The
     hand-over says the internet-facing demo VM uses the same account, so a process on the demo VM could read it.

   What bounds both: each code works once, the holder sets the password at once, an unused code expires (24 h), and
   the accounts are disabled at the session's stop and at the next boot (D-1132).

## A gap for the product: the TLS name

The box's Caddy serves only `TB_TLS_HOSTNAME` (`deploy/identity/Caddyfile`, the site `{$TB_TLS_HOSTNAME}:443`, no
`default_sni`). On the GPU VM that name is the synthetic site's `trialbox.hospa.test`, which no DNS resolves. A
browser opening `https://<address>/` sends no name to match. The demo VM's own Caddyfile sets `default_sni` for
exactly this reason (`deploy/gcp/demo-vm-boot.sh`).

So the session's line tells the owner to add one line to his hosts file (`<address> trialbox.hospa.test`). Making
the box answer under its address needs one of two changes: a product setting for the Caddyfile's `default_sni`
(the installer's and identity's lane), or a site name the owner's DNS resolves. Neither is built here. It is a
question for the integrator. Not checked on a VM: whether Caddy without `default_sni` answers a request that sends
no name.

## Held by

- `tests/unit/test_h13_session_driver.py`:
  - `--links` prints each code once, with the id, the certificate and the stop, then deletes the object; a second
    read finds nothing;
  - no link without the door or with a public bucket;
  - the metadata the launch builds holds no code, link or secret;
  - the VM's step keeps codes in root-only files only and removes them.
- `tests/unit/test_h13_session_door.py` (`links-meta` reads no code).
- The rehearsal cases `session`, `session-stop`, `session-cut`. Every code the console's stand-in made is looked
  for in every boot's output, the serial port, every log and result, the record and the metadata. Each is in the
  links object, as a one-time link, and nowhere else.
