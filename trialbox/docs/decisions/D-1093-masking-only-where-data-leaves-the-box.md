# D-1093 Masking is applied where data leaves the box, by one function, and cannot be turned off there

- **Task:** module M3 (MASK-1, 10G-49; the owner's ruling, #639 comment 7102033134) · **Date:** 2026-11-25
- **Builds on:** D-337 and D-756 (the note masker), D-927 (the log scrubber), D-1354 (the support bundle's scrub),
  D-792 (the tripwire's setting), D-369 (a patient file's named recipients), D-272 (chart numbers in the audit)

## Decision

1. **Inside the box** notes are read as written. Calls to a model on the box are not masked.
2. **What leaves the box** passes one function, `tb_common.egress_edge.leave(route, destination, payload)`. Its rules
   are one table: per route, masked, refused, or an exception. A route that is not in the table, a file it cannot
   read, a masker that fails and a departure that cannot be recorded are refused; nothing leaves.
3. **Three exceptions**, each to its named destination, each audited: a patient file to its named recipients (by mail,
   or by its sign-in link), the EDC write-back, and the national-insurance submission. The patient file asks at each
   send whether every recipient is on the study's delegation log today and whether the person who asked for the job
   is. A no refuses everywhere. An unknown refuses on a PRODUCTION box and is recorded on any other.
4. **The screening log with every chart number** (`/pilot/registry/{study}/export.xlsx`) is not one of the three: it is
   refused when it holds a chart number.
5. **Aggregate files hold no note text**: a field of note text refuses the file.
6. **The tripwire** (`TB_GATEWAY_PHI_TRIPWIRE`) cannot be off on a PRODUCTION box: the gateway does not start. On any
   other box it stays a development switch; the doctor shows it.
7. **The record** is the audit log: one `egress.leave` line per departure or refusal, with the route, the
   destination, the count, the rule, the size, the sha256 and the result, and no identifier. The page "What left this
   box" (`/admin/egress`) reads it.

8. **What is not a patient's stays readable on a mail or an export**: an address of the site's own mail domain, a
   doctor's name with a title or the box's staff code after it (never after a patient's label), a study's own subject
   number, and the telephone, mail and address in a consent form, which a patient must be able to read. The log and
   the support bundle hide these too.

## What it does not do

The rules find named forms: a labelled name, a chart number, a date of birth, a national id, a phone, an address, an
e-mail. A person's name that stands free in running text, a value split by a line break and an encoded value are not
found (the rates are in `docs/validation/masking-sheet.md`). Pixels are not read. What is indexed inside the box is
unchanged here (DB-C6's other half, a later module).
