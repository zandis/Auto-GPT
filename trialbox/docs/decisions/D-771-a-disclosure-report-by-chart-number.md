# D-771 The privacy office's audit report for a chart number

- **Task:** NEW-JRN-6, first half (the deep review of 2026-11-12, JRN-006; `37-remaining-work-split.md`, lane C2's
  queue)
- **PR:** this branch (`agent/NEW-JRN-6-a-disclosure-report-by-chart-number`), from master after train 15
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** T-211c (D-451: the audit browser and one patient's report), D-273 (PV-6: a chart number becomes a
  pseudonym at the opt-out door, capped per person and hour, audited; the pseudonym is never given back), D-380
  (CR-023: a reader without `audit.ids` sees pseudonyms hidden), D-544 (the box says whether it knows the patient)

## The problem

A patient asks "who saw my record" and gives a chart number. The one-patient audit report took a 32-character
pseudonym only ("Chart numbers are not searched here"), and by design no page gives the privacy office a pseudonym
back, so APPI 開示 and PDPA 查詢 requests could not be answered from the console: the office would have to record
an opt-out and read the pseudonym out of its own audit line. **Confirmed by a test** before the change (kept failing
output: `jrn6-fail.txt`).

## The decision

- **The audit browser takes a chart number** (`POST /audit/patients/by-chart`, for the readers of `audit.browse`:
  the privacy office and the steward). The box turns it into the pseudonym at the door as the opt-out door does
  (`console.team.chart_to_pid`, the same `/setup/pseudonym` call, signed as `optout.keep`, which both roles hold):
  the same cap per person and hour (`TB_OPTOUT_LOOKUPS_PER_HOUR`, 429 past it), its own `console.chart_lookup` event
  with `for: disclosure`; the number is never stored.
- **The page has its `/api/v1` twin** (`POST /api/v1/audit/patients/by-chart`, `{"chart_no"}`): the same door, cap and audit, the events with every pseudonym hidden.
- **The report never shows the pseudonym.** The page lists the newest events that name the patient, with every
  pseudonym hidden whatever the reader's rights; it has no filter form, no file and no paging link (those carry the
  pseudonym in their address; a note says when older events exist). The report itself is audited
  (`console.audit_report`, `by: chart`).

- **A number the box holds no patient under is refused** (409: "the box holds no patient under this chart number"),
  so a slip of the hand never reads as "nobody saw this record"; one the box cannot say about is shown with a
  warning to check the number (D-544).
- **The lookup's own lines hide the pseudonym** in the audit browser for every reader (`console.chart_lookup` with
  `for: disclosure`, `console.audit_report` with `by: chart`), so it is not one click away for the privacy office,
  which holds `audit.ids`. The audit chain keeps it, as for every event. The steward, who holds the same rights,
  may make the report too: it is the privacy office's and the steward's tool for a patient's request (D-380).

## The review

One adversarial review: NOT SOUND on the first pass. The pseudonym was one click away (the lookup's own lines in the
browser) and an unknown chart number gave a report that looked complete. Both fixed as above and held by tests, with
the cap shared with the opt-out door (one counter per person and hour) and the form shown only when the workspace,
which has the door, is on.

## Remains

The second half of JRN-006: a request log (access, erasure) with its state; erasure is T-206b's.

## Reuse check

The opt-out door's lookup (`to_pid`, `chart_lookup`), the browser's search and `hide_pids`, the report template. One
new route; no new store or permission.

## Dropped (D-311)

No sign-off step.
