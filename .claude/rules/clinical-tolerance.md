---
paths:
  - "trialbox/**"
---

# Clinical tolerance: the review checklist

Clinical staff are not IT people. The product is forgiving by default. "Fail closed" is not, by itself, a reason
for a stop. Hard-stop only where going on plausibly harms a patient or loses or leaks data. Every other problem
gets a default plus a visible warning, an auto-fix, an ask-once with the reading pre-filled, a kept draft, a retry,
an undo, or a release by a named role with a reason.

## The harm classes (the only reasons for a stop)

PATIENT (the wrong or a dead patient, a model excluding a patient), LEAK (data leaving the box), LOSS (data destroyed
or half-written, no backup path before real data), TAMPER (an update that fails its signature), MACHINE (the host
cannot run it), ROOT (root is needed and absent), SECRET (a secret would be read from or written to a place others
can read).

## The checklist (each pull request is reviewed against it)

1. **Name the harm or do not stop.** A stop, refusal, hold, 4xx for typed input, exact-format demand or manual step
   names one class above in the PR body. No class, no stop: default and WARN.
2. **Stop at second 0 or not at all.** Judge everything a step will refuse before it reads or writes (preflight). A
   refusal after work is a defect.
3. **Default and WARN beats refuse.** The WARN lands where the role looks (the Operations page or "Information still
   needed", the doctor line, the night report) and in the audit. It names the action.
4. **Read typed input before judging it.** Blanks, case, full and half width, date and number forms, leading zeros,
   chart numbers through the site rule: one coercion layer for every form and the mail grammar. An ambiguity is
   asked once with the reading pre-filled.
5. **Never lose what a person typed.** After a failed POST, a stale form, an idle sign-out or a service that did not
   answer, the form comes back with the values.
6. **A limit says the number and when it resets.** A 403 says who can. A hold says who releases it and how.
7. **Every hold has a release**: a named role, a reason field, an audit row. The release never silently merges two
   people or sends data out.
8. **A transient failure is retried once, then a plain sentence.** Never a 500 page.
9. **Undo over confirm** for a reversible act (the study-close take-back is the model).
10. **One plain sentence in en, ja and zh-TW** per message: what happened and what to do. No code, variable or path
    to a non-IT role. The i18n completeness test covers the new key.
11. **The operator can always reach a working box.** No install, update or restore path ends without the box
    running, except the kept classes, which say so and name the fix.
12. **A test for a new stop plants the harm** (the wrong patient, the leak, the loss) and asserts the stop. A test
    that only asserts "it refuses" is not evidence the stop is needed.

## Removing or softening a stop

A diff that removes or softens a stop needs no harm statement. It needs the test that still plants the harm for the
class it keeps, unchanged. A test whose assertion changes because a stop became a WARN is changed only when the PR
body lists the stop, the old and the new assertion, and the check that the kept class still stops.
