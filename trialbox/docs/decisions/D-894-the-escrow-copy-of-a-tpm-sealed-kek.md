# D-894 the escrow copy of a TPM-sealed KEK (TB-SOP-03 §5)

- **Task:** KEK-ESCROW, the integrator's yes on #639 (2026-11-16), as proposed after D-893
- **PR:** this branch (`agent/KEK-ESCROW-recovery-shares-for-a-tpm-kek`)
- **Date:** 2026-11-16
- **Status:** proposed: a security decision (a second way to the KEK, held by custodians). It goes on a train only
  after the owner's yes; the integrator asks him with advice to say yes.

## Decision

1. `python -m tools.keys escrow-shares --threshold K --shares N --escrow-out <media> --custodian <name> ...`
   (`tools/key_escrow.py`) splits the unsealed KEK of a TPM box (back end `file`) into N shares (GF(256), any K give
   it back), one file per named custodian, and records the set in `kek.json`'s `escrow`: set id, K, N, the KEK id it
   opens, the time, each share's custodian and fingerprint. Never a share. The audit event is `keys.escrow`
   (fingerprints and custodian names only).
2. Refused, each with a test: K under 2 or not under N; a custodian count other than N, or a name twice; a media
   folder that is not already there, is inside the secrets folder, is on the secrets folder's or the system's disk, or
   is not removable (sysfs `removable`, or on a USB bus); a box whose back end is not `file`; a second set for the
   same KEK (replace a lost set with `rotate-kek`, so the old shares open nothing); no audit folder; the KEK locked.
3. `python -m tools.keys unseal --share <file> ... --witness <name>` on a TPM box opens the KEK from its escrow
   shares (`tb_common.kek.kek_from_escrow`), for a new board with the secrets volume restored. Refused without a
   witness, with a witness who is an escrow custodian, with too few shares, a share of another set, a set of an older
   KEK, or without an audit folder. It writes the escrow-use record `deploy/site/escrow-use-<time>.md` and `.json`
   (which custodian brought which share, the witness; signed) and the audit event `keys.escrow_unseal`.
4. `rotate-kek --backend file ... --escrow-out <media> --custodian ...` makes a new set with the new KEK (checked
   before anything changes). Without `--escrow-out` the old set stays in `kek.json` only so `doctor` can say it is of
   the old KEK; the command warns.
5. `ceremony-record` lists a TPM box's escrow set (or "Escrow: none"), refuses a set of an older KEK, and refuses
   when an escrow custodian is not among `--custodian` (each signs). `doctor` `key_ceremony` WARNs (never FAILs) on
   an escrow set of an older KEK, and on a set the newest record does not list.
6. TB-SOP-03 §5: who may hold a share (each another named person; neither the box owner alone nor hospital IT alone
   holds the threshold; no one holds two; a custodian is never the witness), and that using the shares is a witnessed
   event with its own record, followed at once by `rotate-kek` onto the new board's TPM.

**Not in scope:** the KMS and passphrase back ends (refused with the reason); the steward-share back end (its shares
are already the recovery copy).

## Test

`tests/unit/test_key_escrow.py` (each refusal; the shares only on the media, 0600, absent from `kek.json`, the output
and the audit; a new board opens the KEK from 2 of 3 as a witnessed event and rotates onto a new set the old shares do
not open; the ceremony record and the doctor). `tests/unit/test_kek.py`, `test_key_ceremony.py` and
`test_trialbox_doctor.py` still pass.
