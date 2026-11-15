# D-718 An `audit.*` event reaches the chain only from the audit's own writer

- **Task:** NEW-SEC-2 (the owner's critical 2 of 2026-11-13; the deep review's SEC-10)
- **PR:** this branch (`agent/NEW-SEC-2-audit-events-only-from-the-audit-writer`), cut from train 14 with the
  security review's fixes (#500) merged in, because it changes the same file (`libs/tb_common/audit_writer.py`)
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-394 (one audit writer through an append-only journal), D-488 (who may say what: the journal
  records the database role, the drain marks a row of another role's family), D-562 (the nightly signed heads),
  T-211a (key rotation endorsed by the old key), the security review's fix for malformed rows (#500)

## The problem

Every service may call the journal's `audit.append`. The family `audit` (the chain's own records) was shared with
the console and the orchestrator, and any other service's row of it was only marked. A compromised service could
send a forged `audit.signing_key_rotated`: the drain wrote it as such, `verify --heads` read it as a key rotation
not endorsed by a trusted key and failed for good, and the nightly signer then refused to sign again. It could
not hide events; it could stop the integrity check (a denial of service of the audit's own proof).

**Confirmed by a run**: a forged rotation sent as the console's role was written under its name, and `verify`
failed on it.

## The decision

- **No service role has the family.** `audit` leaves the shared families of the console and the orchestrator.
  The chain's own records are written by the chain's writers themselves (the drain, the file writer, the host's
  signer); none needs the journal.
- **One named exception**: `audit.head_signed` from the orchestrator's role. The host's nightly signer records its
  head from the orchestrator's container (D-562), and `verify` trusts no event of that name (the signed heads are
  read from the anchor folders).
- **The drain writes any other `audit.*` row from a service under `journal.reserved_name`**, with the name it
  was sent as (`detail.sent_event`), flagged `reserved` (and `role`), so `audit_verify --foreign` lists it. What
  was sent is kept, as the journal's rule is (never dropped); it is never a record of the chain's own family. The
  drain's own family (`journal`) is reserved the same way, so a service cannot send a record that passes for the
  drain's rename. The console's audit browser labels it, in three languages, and shows the name it was sent as.
- **`verify` takes a key rotation only from a record the chain's writer wrote**: a rotation that came through the
  journal (any chain written before this card may hold one) is noted and not taken as a rotation.
- Every service role is tested, and a role the table does not know.

## What it does not do

- The journal's database function still takes the row (it records the role the sender cannot choose); the
  refusal is the drain's. Refusing in the function would change the role script (`deploy/`, lane D's) and make a
  service's request fail on a name; the review asked that the chain not accept it, which this does.
- A compromised orchestrator can still send `audit.head_signed`; verify trusts nothing in it.
- The other review findings on the audit (SEC-11, heads only nightly; SEC-26, missing events) are not this card.

## What the adversarial review changed

One review by a fresh reviewer, by running. Verdict: sound; the attack is closed.

- Ran: case variants, blanks, look-alike letters and a zero-width space in the name, a bare `audit`, the
  drain's own `audit.journal_resync` and `audit.reanchored` from a service, a `journal` key in the fields, a
  rotation inside another event's detail: each was renamed or written under its odd name and flagged, and no key
  was handed over. The legitimate paths hold: the nightly signer, the drain's own record, a rotation by the
  host's tool (which writes the chain itself), the administrator's role.
- Fixed: the new name had no label in the audit browser and its `sent_event` was not shown; a service could send
  `journal.reserved_name` itself (it could be told apart, but now it is renamed like any reserved name).
- **For the owner:** a chain that already holds a forged rotation sent before this card (as the console or the
  orchestrator, whose roles had the family then, so it was not flagged) now verifies, with a note shown by
  `tools/audit_verify.py` and on the console's verify page; earlier notes can push it past the first ten shown.
  Accepting it lets the nightly signing resume; whether it should be louder (a warning, or listed by
  `--foreign`) is the owner's to say.
- Not checked by the reviewer: the real database journal and role script; the signer on a real box.

## Reuse check

The journal's own marks (`flags_of`, `foreign`, `EXACT_EVENTS`, `flagged`) and #500's rule for rows the drain
cannot take as sent (kept under `detail`, marked). Nothing new is built but one name (`journal.reserved_name`).

## Dropped (D-311)

No sign-off step.
