# D-1130 The session's door: tcp:443 from the owner's own range only, proved before any link

- **Task:** lane H, card H-13 (SESSION-DOOR of D-1123 section 7); the integrator's ruling of 2026-11-17 on D-1123
- **PR:** this branch (`claude/lane-h-13-live-session`)
- **Date:** 2026-11-17
- **Status:** proposed
- **Builds on:** D-1123 (sections 2 and 6), D-423 (443 only, no port 80), D-1120 (this boot's lines only)

## Context

The GPU VM `tb-gpu-sim` has no deny rule of its own. The project's `default-allow-ssh` reaches it from any address.
Its tag `tb-gpu-door` opens tcp:443 to the range of an earlier door (GPU hand-over T16). The demo VM solved the same
problem with two rules on its own tag (`deploy/gcp/demo-vm.sh` `up` and `rules_check`). But the demo VM's check asks
only about the demo's tag. The GPU VM carries other tags, and a rule on one of them could reach it unseen.

## Decision

1. **Two rules on a session tag**, made by `deploy/gcp/box-run.sh` before the VM starts:
   - `tb-session-deny`: INGRESS DENY all from 0.0.0.0/0, priority 510, target tag `tb-session`.
   - `tb-session-https`: INGRESS ALLOW tcp:443 from `--session-allow` only, priority 500, same tag.

   The VM gets the tag for the session. No rule is made for port 80 or 22.
2. **The ranges** (`deploy/gcp/session_vm.py parse_allow`, reusing `demo_vm.parse_allow`): public IPv4 only, each
   /24 or narrower, at most four. The word `any`, 0.0.0.0/0, a private range and IPv6 are refused, before any cloud
   call (exit 2). The /24 floor: the session is one person on their own line; the demo's /16 was for two guests'
   unknown providers.
3. **No SSH.** The metadata carries `block-project-ssh-keys=TRUE`. Every boot of a session run stops and disables
   sshd. A later boot that is no session turns sshd back on, so the VM is kept as it was.
4. **The rules check** (`session_vm.py rules-check`) reads `gcloud compute firewall-rules list --format=json` and the
   VM's own tags. It holds only when:
   - the allow is tcp:443 alone, from exactly the given ranges, at priority 500, on the session tag alone;
   - the deny is all protocols from 0.0.0.0/0 at priority 510 on the session tag;
   - the VM carries the tag;
   - no other enabled allow rule reaches the VM at a priority below 510. The demo's `reaching_rules` is asked once
     for each tag the VM carries, so the old door on `tb-gpu-door` is seen.

   Every rule that applies to the VM is listed with its verdict. `default-allow-ssh` and `tb-gpu-door` read "beaten
   by tb-session-deny". The check runs:
   - in the launch, after the rules are made and before `instances start` (exit 7 when it fails);
   - in `--session-status`;
   - in `--links`, before any link is printed (exit 3, the object left unread).
5. **Free.** `--preflight` and `--dry-run` print the two rules the launch would make (`session_vm.py plan`) and refuse
   a range that is too wide. They make no cloud call.
6. **The bucket is private.** The launch and `--links` read the bucket's IAM policy and refuse it when it names
   `allUsers` or `allAuthenticatedUsers` (D-1123 section 6, "a public bucket").
7. **Taken away.** `--stop` and the end of a collect remove the tag from the VM and delete both rules
   (`session_door_down`). The project's own rules are not touched.

## Held by

`tests/unit/test_h13_session_door.py` (the ranges, the plan, the check against the hand-over's network and eight
ways in), `tests/unit/test_h13_session_driver.py` (the launch makes and proves the door before the start; a door
that does not hold stops the launch; `--links` refuses without the door or with a public bucket; `--stop` takes it
away), the rehearsal case `session-wide` (the driver refuses five wide ranges, no VM booted).

## Not verified

No rule was made on the real project. The VM's network is read from the instance (`default` on the hand-over). The
priority of the real `tb-gpu-door` rule is not known here: the check reads it at the launch.
