# D-546 A typed chart number is held to the site's pattern after it is written the site's way

- **Task:** NEW-DIN-3c (from lane D's review of D-579, given to lane C by the integrator; DIN-003's group)
- **PR:** this branch (`agent/NEW-DIN-3c-pattern-after-normalise`), stacked on #387's head `d9332326`
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI)
- **Builds on:** D-301 (`tb_common.chartno`), D-579 (the rule is asked at install, with the pattern that goes
  with it), D-591 (a number wider than the rule keeps its zeros)

## The problem

With the rule `digits:8` the site's pattern is `^\d{8}$`. Every path hashes a chart number after the rule has
written it the site's way: `123456`, full-width digits and `00123456` are one patient. Three places matched the
pattern against the number as typed, before the rule: the registry's row typed by hand
(`orchestrator.candidates`), a CASE request's chart number (`orchestrator.scenarios.case`) and a chart given to
site set-up (`sitesetup.service.add_chart`). A coordinator who typed `123456` was refused, although the box
would have found the patient.

## The decision

The three places match the pattern against `chartno.normalise(None, <typed>)`. Nothing else changes: the number
is hashed as before (the hash normalises by itself), and a number the rule does not make fit is refused as
before: one that is too long (never cut), one that is not digits, one wider than the rule (D-591 keeps its zeros,
so it does not fit).

## What it does not do

- For a pattern that fits the rule (the pairs the installer writes, D-579) it refuses fewer numbers, never
  others: every number accepted now is one whose normalised form fits the pattern, and that form is what is
  hashed. No number reaches another patient than before. With a pattern set by hand that does not fit the rule
  (`digits` without a width and `^\d{8}$`; a hex rule and a pattern of the other case) a number that was accepted
  as typed is now refused, because the form that would be hashed does not fit: the safe side.
- The opt-out desk's shape check (`console.team`: letters, digits or `-`) is not the site's pattern and is not
  changed here; it refuses full-width digits before the box is asked. That file is in two open cards (#394,
  #406); the change can follow them.
- Under the rule `asis` nothing changes but blanks and full-width forms, which the rule already removes.

## What the adversarial review changed

One review by a fresh reviewer. Verdict: fix first, one MED. The property that matters held in every rule and
input it ran: what is hashed is exactly the form that was matched, and no two numbers become one.

- **MED-1, a fault this card made:** site set-up masks the chart number in the stored chart text by replacing
  the typed text. Before, the pattern forced the typed text to be the whole number. With this card `2` is
  accepted for chart `00000002`, and every `2` in the chart became `[MRN]` (`9.[MRN] mg/dL`). The masking now
  replaces the number as the site writes it, and a typed spelling only when it is as long. Test with typed `2`.
- **LOW:** the sentence above about "fewer numbers" was too wide and is corrected; the set-up test asserts the
  error's type.

## Reuse check

`tb_common.chartno.normalise` covers it: the change is three calls of it.

## Dropped (D-311)

No sign-off step.
