# D-1092 A PRODUCTION box rotates its exposed KEK passphrase under rc1 (H-97)

- **Task:** lane H, card H-97 (the integrator's ruling 7101844662; finding H96-04 of H-96) · **Date:** 2026-11-23
- **Status:** reserved for H-97 (the integrator flips the row when merged)
- **Builds on:** D-1072 and review R22-34 (what rc1 refuses on a PRODUCTION box), D-127 (a box is PRODUCTION unless
  it says otherwise), H-96 (the KEK passphrase from a root-only file or stdin, never the environment)

## Context

rc1 refuses the key ceremonies on a PRODUCTION box (`tb_common.rc1_refusals`, row `key_ceremonies`), and
`tools.keys rotate-kek` was one of them. A box installed with the passphrase in the environment before H-96 holds
that passphrase in its system journal (H96-01, H96-03), so it must rotate it. Under rc1 a PRODUCTION box could not,
and the page sent it to the vendor (H96-04).

## Decision

1. **Rotating a leaked key is a safety action, not a ceremony.** On a PRODUCTION box rc1 lets `rotate-kek` through
   when, and only when: the box is sealed under a passphrase (`kek.json` back end `passphrase`); the new KEK is a
   passphrase (`--backend passphrase`); the new passphrase comes from H-96's file or stdin form
   (`--new-passphrase-file` or `--new-passphrase-stdin`); and no escrow set is made (`--escrow-out` is not given).
2. **It is audited.** The rotation needs the audit folder (`--audit-dir`, else `TB_AUDIT_DIR`); without one it is
   refused before anything is read or written. When the keys are re-wrapped it writes one event `keys.rotate_kek`:
   who (the user it runs as and the kernel's login uid, never a variable of the caller), when, the box's host name,
   the environment, the old and the new KEK's ids and `D-1092`. Never a passphrase or a key.
3. **rc1's other refusals are unchanged.** Every other `rotate-kek` on a PRODUCTION box (to the TPM, the file, steward
   shares or a KMS; with an escrow set; with the new passphrase typed at the prompt without `--new-passphrase-stdin`;
   on a box not sealed under a passphrase), the ceremony record, escrow shares, the restic key, the pid map key's
   rotation and the backup key ceremony stay refused with the same words and exit code. The environment is the
   stricter of the box's and the caller's, as before.
4. RUNBOOK §23 "Rotate the KEK passphrase" says a PRODUCTION box rotates itself; the section stays a section.

Proved by `tests/unit/test_rotate_exposed_passphrase_h97.py`. The card's page:
`docs/handover/first-run-code-h97-2026-11-23.md`.
