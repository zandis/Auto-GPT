# D-717 Every route of the orchestrator that returns a patient's row checks the verified person and the study

- **Task:** NEW-SEC-1 (the owner's critical 1 of 2026-11-13; the deep review's SEC-07)
- **PR:** this branch (`agent/NEW-SEC-1-patient-reads-check-person-and-study`), cut from train 14
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-483 (the acting person of a route; actor assertion v3), D-550 / D-554 (routers moved to
  `refuse`), D-464 (which service may call which route), D-380 (the matrix), D-389 (the monitor's grant)

## The problem

The deep review found, by running, that the data core's patient-level reads at the orchestrator (`GET
/studies/{rs}/data`, `/records`, `/export`, `/fhir`) carried no person and no study check: the console's token
alone read every record of any study, and the export's audit named whoever the query string said. The console was
the only check.

**Confirmed and widened by a run**: of the 26 GET routes of the orchestrator that return a patient's row, 25
answered a bare console token (the data core's six, the lifecycle's six, the REDCap read-back, four of the EDC's,
the registry's two, the set-up's six). Only the enrolment report as a file checked.

## The decision

- **Every GET route is in one of two lists.** `tb_common.patient_reads` lists the 26 reads that return a
  patient's row ("a record of one patient's data, by pseudonym or record key, and a list of such records");
  `route_actors.yaml` (`reads_without_patient`) lists the 32 others, each with its reason (counts, settings, a
  study's definition, a job's record, FastAPI's own pages). A GET route in neither list stops the orchestrator at
  import (`route_problems`, as for a changing route) and fails the test.
- **A patient read takes a verified v3 claim** (`require_actor`): for `phi.view` (who may see patient-level data)
  on the route's own study (`{rs}`, or `{ruleset}` on the registry's); the matrix is asked again. A set-up route of
  the whole site (`/setup/{ws}/...`) checks a claim that names no study. The four reads of the monitor's page (the
  subjects, a subject, the EDC drafts, a record's trail) take `monitor.read` too (a sponsor's CRA under a monitor
  grant, D-389); the claim names which, and the matrix is asked for that one.
- **Each is held by a test, route by route**, on the real app in the production trust configuration: no claim, a
  claim for another study, a role without the right, and a claim for another action are refused (403, one
  `actor.refused` each); a coordinator's claim passes.
- **The console signs those reads from the request's account.** Where the session is taken (the pages' and the
  API's), the account is bound for the request (a context variable); every orchestrator GET that is a patient read
  is signed for the first of its actions the account holds in that study, or refused at the console
  (`console.denied`). A page's helpers did not change: the signing is in the one call path (`s28.call`, the
  registry's).
- **A timer reads as its principal**: the morning mail (visits, subjects, serious AEs) signs as
  `service:console-notify`, which `route_actors.yaml` now lets take `phi.view`; a principal passes only where the
  table lists the action for it.
- The data core's export names the verified person of the call; it no longer takes a typed `?by=`.

## What it does not do

- **Job records** (`GET /jobs`, `/jobs/{job_id}`) are classified as no patient's row: a job's type, state,
  options and the names of its files; the rows are in the files, which the console reads from the object store.
  A CASE job's options name its subject's pseudonym. The operator's and the mail gateway's tokens still read them.
  Said here; the owner's to say if a pseudonym in a job's options is a patient's row.
- **The two EDC reads that already checked an EDC role** (the copy sheet, the ODM export) keep that v2 check in
  their handler, now behind the v3 one; their `by` query stays as the v2 fallback name, refused outside DEV and
  TEST (D-162).
- The changing routes of the data core and the set-up stay in stage `report` (D-483): this card is about reads.
- The console's own page gates are unchanged; the orchestrator now holds the same line itself.

## Review

See "What the adversarial review changed" when the review is in.

## Reuse check

`orchestrator.actor.require_actor` and its walk (`walk`, `route_problems`), the console's `assert_for` and
`assert_service`, the test helpers `tests.actor3.signed` / `SignedClient`. Added: the shared list
`tb_common.patient_reads`, the console's `read_headers` / `bind_reader` / `reading_as`, and a signed-read helper
for tests (`OrchBox.read`).

## Dropped (D-311)

No sign-off step.
