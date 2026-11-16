# D-893 the key ceremony has a record the custodians sign (TB-SOP-03)

- **Task:** KEY-CEREMONY, the integrator's yes on #639 (2026-11-16)
- **PR:** this branch (`agent/KEY-CEREMONY-the-record-the-custodians-sign`)
- **Date:** 2026-11-16
- **Status:** accepted

## Decision

1. `python -m tools.keys ceremony-record --custodian <name> ... --witness <name> [--shares-dir DIR]`
   (`tools/key_ceremony.py`) writes `deploy/site/key-ceremony-<time>.md` (printed and signed) and `.json`: each
   wrapped key's fingerprint, the KEK's back end and id and what that back end means after a power loss and when a
   custodian leaves, for steward shares the threshold, the count and which custodian took which share (with each
   share file's fingerprint when the files are given), the backup key's fingerprint, the site, environment, release
   and time, and a signature line for each custodian and the witness. Fingerprints and names only: no key, share or
   passphrase. It is refused before `keys init`, while a key is plain or the custody has a problem, when a share has
   no named custodian, and when the witness is a custodian. A passphrase box's record is marked "not a site's key
   ceremony". The ceremony is the audit event `keys.ceremony`.
2. TB-SOP-03 is `docs/security/10-key-ceremony-and-escrow.md`: who attends, the back end as the box owner's and
   hospital IT's choice at the ceremony (the TPM the default, steward shares the other), what each means after a
   power loss and when a custodian leaves, the commands in order, escrow, rotation and compromise.
3. `trialbox doctor` `key_ceremony` WARNs on a VALIDATION or PRODUCTION box with a KEK and no record, or a record of an
   older KEK (after `rotate-kek`). A WARN, never a FAIL: no install gate. RUNBOOK §6 names the record as IQ-05's
   evidence.

**Not built, said in the SOP:** the integrator asked for the TPM as the default with steward shares as the recovery
copy. The tooling makes shares only when steward shares are the back end; there is no escrow copy of a TPM-sealed
KEK, so a dead board leaves the wrapped site keys unopenable. A follow-up card is proposed on #639.

## Test

`tests/unit/test_key_ceremony.py` (7): refused before init and while a key is plain; a shamir record names one
custodian per share with the share files' fingerprints, the key fingerprints and the backup key, and holds no key or
share text (in the record, the Markdown, the output); one custodian per share and a witness who is not a custodian;
a passphrase box's record says it is not a site's ceremony; every back end says what it means and the SOP holds what
the integrator asked; the doctor WARNs on a site box without a record and passes once there is one, never FAILs.
`test_trialbox_doctor.py`'s list of checks gains `key_ceremony`.
