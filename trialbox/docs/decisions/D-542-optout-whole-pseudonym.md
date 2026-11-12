# D-542 The opt-out register takes a chart number or the whole pseudonym, and says what matched

- **Task:** NEW-JRN-2 (`docs/plan/33-plan-v7.md` section 5, wave 0, lane C; TB-PLAN-07)
- **PR:** this branch (`agent/NEW-JRN-2-optout-whole-pseudonym`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI)
- **Measures:** closes JRN-002 (Critical) of `docs/reviews/2026-11-12-deep-review/04-user-journeys.md`; DIN-003's
  console half is a card of its own (NEW-DIN-3)
- **Builds on:** D-147 (the opt-out register), D-273 (PV-6: the register gives no pseudonym back; a chart number
  typed at the door is a capped, audited lookup), D-380 (the steward or the privacy office keeps the register)

## Context

Every screen shows a patient by the first eight characters of the pseudonym. The register accepted any text of 8
to 64 characters as a pseudonym. Typed as shown (`e7543f47`), an opt-out was stored for those eight characters and
the page answered "Recorded: the patient opted out. The patient is removed from screening, lists and later
exports." The patient stayed on the PI's list. A mistyped pseudonym was confirmed the same way. A patient who
opted out kept being screened and listed while the register showed an opt-out: a failure nobody could see.

## The decision

1. **A typed pseudonym is whole or it is refused.** 32 hexadecimal characters (`tb_common.crypto.PID_HEX_LEN`),
   after spaces are trimmed and capitals lowered. Anything else is a 400 that says: type the whole pseudonym or
   the chart number; the eight characters a page shows name no patient. The page and `/api/v1` share the rule.
2. **The page says what matched.** For a typed pseudonym the console reads, before the opt-out removes them,
   which studies' registries and current lists hold it. After the save the page says "The patient was on the list
   or registry of: ..." or, when none does, a warning that no patient with this pseudonym is on a list or
   registry of this box today. The opt-out is kept either way: a patient may opt out before any list names them.
   `/api/v1` answers `matched` (a count). Neither gives the pseudonym back (D-273).
3. **A chart number** is turned into the pseudonym by the box as before (capped, audited). Its match is not
   shown: whether the box knows that patient is NEW-DIN-3 (the orchestrator answers it from the pid map).
4. **Old rows.** A register row made before this rule for a short text names nobody. Its "take back" on the page
   still works (the form posts the row's own text, and a lift is accepted for a text that is on the register);
   nothing else is accepted short.

## What it does not do

- It does not refuse a whole pseudonym that matches nobody: the console cannot know every patient of the box
  (only the lists and registries it reads), and an early opt-out is legitimate. It warns.
- It does not resolve a unique short form to its patient (the finding's other suggestion): that would turn the
  register into a lookup by prefix, which D-273 keeps out.
- It does not clean old short rows by itself; the keeper sees them on the register and takes them back.
- The shared library (`tb_common.optout`) still accepts 8 to 64 characters: other writers (the restore, the
  adapter's own register feed) are not changed here.

## Dropped (D-311)

No sign-off or owner review step.
