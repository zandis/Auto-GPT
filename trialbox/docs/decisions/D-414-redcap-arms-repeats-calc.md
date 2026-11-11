# D-414 REDCap arms, events and repeating instruments; calculated fields; erase hidden values

- **Task:** T-302b (second part of T-302; `docs/plan/28-master-plan-v6.md` §6.2.5)
- **PR:** this branch (`agent/T-302b-redcap-arms`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Builds on:** D-129 (built-in capture: what it left undone), D-160 (EDC prefill), D-162 (the send's refusals),
  D-281 and D-391 (signatures, T-205), D-368 (T-115: what a draft was built under), D-311 (no development gates)
- **Closes:** CR-062 (the rest: arms and repeating instruments are handled, not refused), LIFE-021 (the arms half)

## Context

The EDC prefill refused a REDCap project with repeating instruments or events (review E-05: a flat export has one
row per repeat, so the "never overwrite" check could not hold). Arms were not read: a value could be written to an
event of another arm. A value for an instrument not designated for the event made REDCap refuse the whole import.
Calculated fields were never computed, and branching logic was not applied on the send, so TrialBox could write a
value that REDCap hides, and REDCap's "erase hidden values" had no counterpart (D-129, "Not done").

## Decision

1. **A visit names one row of the record.** The drafts, decisions and signatures stay keyed by record and visit, so
   nothing in the store or the signature changes (T-205's code is untouched). The visit is `<event>` for the base row
   of an event (`event_1_arm_1` in a classic project), `<event>__<instrument>__<n>` for instance `n` of a repeating
   instrument, `<event>__<n>` for instance `n` of a repeating event. It fits the console's visit pattern
   (`edc.layout`).
2. **The send reads the project's layout and places each value or holds it back.** Per send: `content=project`,
   `event`, `formEventMapping` and `repeatingFormsEvents` (`edc.layout.Layout`). A value is held back, listed with its
   reason and kept in `sent`, when its visit is no event or instance of the project (`no_event`), its instrument is
   not designated for the event (`not_on_event`), the record already has rows on another arm (`wrong_arm`), it is a
   repeating instrument's field on the base row (`repeating_form`), or it is another instrument's field on an
   instance row (`not_repeating_form`). The import row carries `redcap_repeat_instrument` and
   `redcap_repeat_instance`; the conflict check, the "already there" check and the read-back are keyed by record,
   event, instrument and instance.
3. **Fail closed on repeats REDCap does not describe.** A project that says it repeats but does not answer
   `repeatingFormsEvents` is refused as before (`edc.repeating`). A project that repeats but whose export has no
   `redcap_repeat_instance` column is refused whole (`edc.repeat_keys`): nothing is sent.
4. **A small evaluator of REDCap's logic, never `eval`.** `edc.logic`: a tokenizer, a recursive-descent parser and
   an interpreter over the tree, with limits on length (4000 characters), tokens (1000) and depth (40). It reads
   field, event, checkbox-code and instance references, numbers and text, arithmetic, comparisons, `and`/`or`, and
   `if`, `sum`, `mean`, `median`, `min`, `max`, `round`, `roundup`, `rounddown`, `abs`, `sqrt`, `exponential`, `log`,
   `datediff`, `isnumber`, `isinteger`, `contains`, `not_contain`, `starts_with`, `ends_with`. Blanks follow REDCap
   (a blank in arithmetic is blank; `sum` and friends skip blanks; a division by zero is blank; an order comparison
   with a blank is false; `round` rounds half away from zero). Anything else (smart variables, other functions)
   raises: TrialBox then does not know and says so.
5. **Branching logic on the send.** With the values about to be sent laid over the row as REDCap holds it, a value
   for a field REDCap would hide is not sent (`hidden`); logic TrialBox cannot read holds the value back (`logic`).
   Holding one value back can hide another, so the check repeats until nothing changes.
6. **Calculated fields are compared, never written.** The map already refuses a calculated item. After a send, each
   calculated field of each row written is computed by TrialBox and listed beside the value REDCap computed
   (`calc`, with `equal`); the audit counts the differences. `EdcService.preview` shows the same before a send, for
   the decided values of one subject and visit, with the values that would not be written and why.
7. **Erase hidden values, only TrialBox's own.** After a send, values REDCap now hides are listed
   (`hidden_in_redcap`, with whether TrialBox wrote them). `EdcService.erase_hidden` erases, on one row, each hidden
   field whose REDCap value is the one TrialBox last sent there (`overwriteBehavior=overwrite`, that field alone),
   reads it back and keeps an `erased` row in `sent`; a hidden value someone else wrote is listed and never erased.
   Audited as `edc.erase_hidden`, refusals too; refused for an opted-out patient.
8. **ODM carries the repeat keys.** A value on an instrument instance is written in `FormData` with `FormRepeatKey`
   (its `FormDef` says `Repeating="Yes"`); one on a repeating event's instance in `StudyEventData` with
   `StudyEventRepeatKey`. The simulator's ODM import reads both back onto the instance rows.
9. **The simulator repeats like REDCap.** `rc_sim` answers `repeatingFormsEvents`, exports the repeat columns on every
   row of a repeating project, keys rows by record, event, instrument and instance, refuses a field on the wrong row,
   takes `overwriteBehavior=overwrite`, and computes calculated fields on import with `edc.logic` (REDCap computes
   them on import too). `POST /sim/projects` takes arms, instrument designations and the repeating set.
10. **Drafting an instance drafts only that instrument's items.** A base-row draft still drafts every mapped item;
    the send holds back what does not belong on the row.

## Not in this decision

- The console page for `preview` and `erase_hidden` (the service and its rules are here; a page or a route is for
  T-302c, which owns the EDC pages next).
- ODM import into TrialBox, sponsor readers (T-302d); copy-assist (T-302c).
- Missing-data codes, `isblankormissingcode`, smart variables and action tags (`@CALCTEXT`, `@CALCDATE`): outside
  the evaluator, so a field that uses them is held back (`logic`) or its calculation listed as unread.
- A run against a real REDCap project with repeating instruments (CR-062's "never run on a real REDCap" stays open
  until a site sandbox exists).
