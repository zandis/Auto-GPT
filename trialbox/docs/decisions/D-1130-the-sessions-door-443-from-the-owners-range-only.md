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
   - the deny is all protocols from 0.0.0.0/0 at priority 510 on the session tag, to every address of the VM: no
     `destinationRanges`, 0.0.0.0/0, or ranges that hold the VM's internal and external addresses (the re-review's
     B) and each of its alias IP ranges whole (round 3's finding 6);
   - the VM carries the tag;
   - no other enabled allow rule reaches the VM at a priority below 510. The demo's `reaching_rules` is asked once
     for each tag the VM carries, so the old door on `tb-gpu-door` is seen;
   - the allow names no `sourceTags` and no `sourceServiceAccounts` (other VMs of the project would reach 443). Both
     rules are deleted and made again at a launch, never kept or updated, so nothing added to them survives. The
     deny's description names its run (`run=<id>`);
   - the VM has one network interface and no IPv6 address (`gcloud compute instances describe --format=json`):
     the deny names 0.0.0.0/0, and the rules of one network are read;
   - no firewall policy lets traffic in. Hierarchical and network firewall policies are evaluated before the VPC
     rules and are not in `firewall-rules list`, so the VM's effective firewalls are read
     (`gcloud compute instances network-interfaces get-effective-firewalls`): any ingress rule of a policy whose
     action is not `deny` or `goto_next` fails the check (`allow`, `apply_security_profile_group`, or an action added
     later: the re-review's B).

   Every rule that applies to the VM is listed with its verdict. `default-allow-ssh` and `tb-gpu-door` read "beaten
   by tb-session-deny". The check runs:
   - in the launch, after the rules are made and before `instances start` (exit 7 when it fails);
   - in `--session-status`;
   - in `--links`, before any link is printed (exit 3, the object left unread).
5. **Free.** `--preflight` and `--dry-run` print the two rules the launch would make (`session_vm.py plan`) and refuse
   a range that is too wide. They make no cloud call.
6. **The bucket is private** (D-1123 section 6, "a public bucket"; D-1133 item 5). The launch and `--links` read the
   bucket (`gcloud storage buckets describe`) and its IAM policy and refuse it unless: no binding names `allUsers`
   or `allAuthenticatedUsers`; uniform bucket-level access is on or public access prevention is enforced (no object
   ACL can make the links object public); versioning is off (a deleted links object leaves no readable version).
7. **Taken away, in two steps.** `--stop` and the end of a collect delete the allow at once, and so does a collect's
   first look at a session VM found TERMINATED (a pre-emption). The deny-all and the tag stay until the run the
   deny names has its `CLOSED` marker beside its links (D-1132 item 7), whichever run's `--stop` is asked (the
   re-review's D): until then nothing, not the old door and not SSH, reaches the VM. A later `--stop` then removes
   them, with any links object of that run nobody read (its codes are dead). The project's own rules are not
   touched. The deny is never removed while the allow may exist (round 3's finding 5): the allow is deleted and
   confirmed gone (gcloud says "not found") first; else the deny-all and the tag stay.
8. **Nothing outlives a session into another launch** (the re-review's A). Before any launch, resume or power cycle
   (G-9, from a collect: round 3's finding 3) starts the VM, an earlier session's allow is deleted. Its deny and tag go when the run the deny names has its `CLOSED`
   marker; else they stay, and a launch that is no session goes on behind them (its boot closes those accounts
   first, D-1132 item 7), while a new session launch is refused (exit 7). A launch refused after its door was made
   (exit 7) takes the door away again. A rule the driver cannot read is never taken for "not there" (round 3's
   finding 2): `rule_exists` tells gcloud's "not found" from any other error; on an error a start is refused (exit 7,
   the VM left off) and a `--stop` keeps the deny and the tag.
9. **Run ids.** A run id given to `--links`, `--session-status`, `--collect`, `--stop` or `--resume` must be of the
   VM's own form (letters, digits, `.`, `_`, `-`; no `..`), checked before any cloud call. `--links` and
   `--session-status` take `--session-allow` for the ranges when the run folder is not on this machine.

## The security review of 2026-11-17

The lead's adversarial review found five blind spots of the first build, each reproduced: an allow carrying source
tags or service accounts, an IPv6 allow-all, firewall policies, a second interface, and a bucket made public by an
object ACL or kept by versioning. Items 4, 6 and 7 above close them; each has a test that failed before.

## The re-review of 2026-11-17

An independent re-review of the fixes found two more ways the door could fail: a deny narrowed by destination ranges
(kept as it was), and an allow left by a session nobody stopped or by a refused launch (exit 7), which a later launch
neither checked nor removed. A firewall policy's other actions counted as no way in. Items 4, 7, 8 and 9 close them;
each has a test that failed before.

## Round 3 of the re-review (2026-11-17)

A second independent re-review found four more ways around the door, each with a test that failed before:

- a describe error read as "no rule" (finding 2, item 8);
- a power cycle that started the VM without looking at an earlier session's allow (finding 3, item 8);
- a deny removed while the allow's delete had failed (finding 5, item 7);
- an alias IP range the deny's destination ranges did not hold (finding 6, item 4).

Its finding 1 (the box's own `trialbox.service` at a boot) and 4 (a later boot of a session run) are D-1132's items 7,
9 and 11. Its finding 7 is stated here, with no code:

- `--stop` or `--collect` of any older run deletes the allow of a session that is live now. It fails closed: the
  owner's page stops answering (availability only); the deny and the tag stay until that session's `CLOSED`.
- A start that goes around the driver (by hand, or after `reset_vm` put the plain `gpu-sim-startup.sh` back) runs no
  close: the session's accounts stay open on the disk. The kept deny-all bounds it: nothing from outside reaches the
  VM until a box run's boot closes them (D-1132 item 11).

## Held by

`tests/unit/test_h13_session_door.py` (the ranges, the plan, the check against the hand-over's network and eight
ways in), `tests/unit/test_h13_session_driver.py` (the launch makes and proves the door before the start; a door
that does not hold stops the launch; `--links` refuses without the door or with a public bucket; `--stop` takes it
away), the rehearsal case `session-wide` (the driver refuses five wide ranges, no VM booted).

## Not verified

No rule was made on the real project. The VM's network is read from the instance (`default` on the hand-over). The
priority of the real `tb-gpu-door` rule is not known here: the check reads it at the launch.
