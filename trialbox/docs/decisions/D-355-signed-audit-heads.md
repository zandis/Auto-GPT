# D-355 Signed audit heads, off-box anchor folders, and the clock as a FAIL

- **Task:** T-211a (wave 2 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.5)
- **PR:** this branch (`agent/T-211a-audit-anchors`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Builds on:** D-272 (the head anchor), D-347 (the site keys under a KEK)
- **Closes:** CR-042 (signing part; one writer is T-211b), CR-054 (rest), DATA-021, OPS-055

## Context

D-272 gave the audit chain a head anchor (`HEAD.json`), but the anchor is not keyed. A process that can write the
audit volume can remove a line, recompute every hash after it and rewrite `HEAD.json`: `verify` then passes
(DATA-021, CR-042). The IRB amendments and the IT pack promise a daily signed head with a copy on the hospital share.
The clock check was a WARN (OPS-055, REG-026), although audit times and sign-in codes depend on it.

## Decision

1. **The audit key.** An Ed25519 key, `audit_sign.key` in the secrets folder, made by
   `tools/audit_verify.py --init-key` with the existing `tb_common.crypto` functions. It is wrapped under the KEK of
   D-347 when the folder has one, and refused plain in VALIDATION and PRODUCTION. Its public key is `audit_sign.pub`.
   The key id is the public key's fingerprint.
2. **Signed heads.** `AuditLog.sign_head` (CLI `--sign-head`) signs the chain as it stands: event count, last hash,
   file and time. It signs only a chain that verifies, and only when the key is the pair of its public key. It then
   records an `audit.head_signed` event (count, hash, key id, how many folders took it, which failed).
3. **Off-box anchor folders.** The signed head goes to every folder in `TB_AUDIT_ANCHOR_TARGETS` (or `--to`):
   local paths, such as the mounted hospital share. No cloud service. A folder inside the audit folder is refused.
   Files are write-once (`heads/<time>-<count>.json`, `keys/<key id>.pub`); a different file of the same name is
   never replaced. The CLI exits 1 when any folder did not take the head.
4. **Verify.** `--heads DIR` checks every signed head of an anchor folder: a valid signature of a trusted key, and
   event `n` of the chain has the signed hash. A removed and recomputed line fails, even with `HEAD.json` rewritten.
   Asking for signed heads and finding none fails. Trusted keys come from `--pubkey`; without it, from the anchor
   folder's `keys/`, and the output says so.
5. **Rotation.** `--rotate-key` writes an `audit.signing_key_rotated` event that the old key endorses. A new key is
   trusted only through such an event. A head signed by the old key over events after the rotation is refused, and a
   rotated-out key endorses no other key. The new key waits as `audit_sign.next.key` until the event is written, so
   a run cut short is finished by running it again.
6. **The clock.** `tb_common.audit.clock_state` reads the kernel's NTP state (`adjtimex`, read only) and, when
   `TB_NTP_SERVER` is set, the offset from the site's time server (one SNTP exchange). `doctor` check `clock` FAILs
   beyond `TB_CLOCK_MAX_SKEW_S` (default 60 s) in every environment. In VALIDATION and PRODUCTION it also FAILs when
   the clock is not synchronised, the server does not answer, or neither can be read; in DEV and TEST those are WARN.

## Consequences

- The nightly timer that runs `--sign-head`, the weekly admin mail with the head, and the share mount are deploy
  work, not in this change.
- Refusing a job start at 61 s skew needs the orchestrator; `clock_state` is the function it will call.
- `deploy/check_host.sh` still prints a WARN for the clock; doctor is now the FAIL.
