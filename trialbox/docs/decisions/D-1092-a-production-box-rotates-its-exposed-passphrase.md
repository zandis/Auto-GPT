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
5. **Every rotation is audited** (the integrator's ruling 7114085298, after this decision's first form): on every box,
   PRODUCTION or not, `rotate-kek` writes `keys.rotate_kek` (as in 2, with the environment and the new back end) and
   is refused without its audit folder. The event's `rule` says `D-1092` for the PRODUCTION exception and
   `7114085298` elsewhere.
6. **Audited first, safe when cut short, one at a time** (the review of #1429, F1 to F5). The audit folder must hold
   the box's chain (`HEAD.json`). `keys.rotate_kek_started` is written before any key file changes, and a rotation
   whose started event cannot be written is refused; `keys.rotate_kek` follows once `kek.json` names the new KEK. Run
   as root against a folder another user owns, each append is made as that user. A journal in the secrets folder
   (`kek-rotation.json`, no key) names the step, so the next `status --audit-dir` or `rotate-kek` rolls a rotation
   cut short back (before its commit) or finishes it (after), and says so in the chain. An exclusive lock on the
   secrets folder refuses a second rotation while one runs.

Proved by `tests/unit/test_rotate_exposed_passphrase_h97.py` and `tests/unit/test_rotate_kek_safety_h97.py`. The card's page:
`docs/handover/first-run-code-h97-2026-11-23.md`.
