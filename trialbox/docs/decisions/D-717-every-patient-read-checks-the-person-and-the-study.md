# D-717 Every GET route of the orchestrator that returns a patient's row checks the verified person and the study

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

- **Every GET route is in one of two lists.** `tb_common.patient_reads` lists the 28 reads that return a
  patient's row ("a record of one patient's data, by pseudonym or record key, and a list of such records");
  `route_actors.yaml` (`reads_without_patient`) lists the 30 others, each with its reason (counts, settings, a
  study's definition, a job's record, FastAPI's own pages). A GET route in neither list stops the orchestrator at
  import (`route_problems`, as for a changing route) and fails the test.
- **A patient read takes a verified v3 claim** (`require_actor`): for `phi.view` (who may see patient-level data)
  on the route's own study (`{rs}`, or `{ruleset}` on the registry's); the matrix is asked again. A set-up route of
  the whole site (`/setup/{ws}/...`) checks a claim that names no study. The five reads of the monitor's page (the
  subjects, a subject, the EDC status, the EDC drafts, a record's trail) take `monitor.read` too (a sponsor's CRA under a monitor
  grant, D-389); the claim names which, and the matrix is asked for that one.
- **Each is held by a test, route by route**, on the real app in the production trust configuration: no claim, a
  claim for another study, a role without the right, and a claim for another action are refused (403, one
  `actor.refused` each); a coordinator's claim passes.
- **The console signs those reads from the request's account.** Where the session is taken (the pages' and the
  API's), the account is bound for the request (a context variable); every orchestrator GET that is a patient read
  is signed for the first of its actions the account holds in that study, or refused at the console
  (`console.denied`), as it is for a study the account does not see. A page's helpers did not change: the signing is in the one call path (`s28.call`, the
  registry's).
- **A timer reads as its principal**: the morning mail's whole round (`notify.collect`, and the lifecycle's mail)
  signs as `service:console-notify`, which `route_actors.yaml` now lets take `phi.view`, and only on the reads the
  mail makes: visits, AEs, subjects, a subject and the registry's rows (`service=True` on those routes alone).
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

### What the adversarial review changed

One review by running (a fresh reviewer, real orchestrator box in the production trust configuration, and the
console's site box). It found:

1. **The morning mail lost the registry's statuses** (critical): the N1/N2 round read `GET /registry/{ruleset}`
   outside `reading_as`, the orchestrator refused it, and `registry_map` read the refusal as "no status", so a
   declined patient came back as new in the mail; an administrator's "Send notices now" did the same. Now the
   whole round (`notify.collect`) reads as `service:console-notify` whoever started it, and a refused read in a round
   is an error (`registry_map` returns nothing only to a page's account without the right, which the console has
   already refused and audited). Held by `tests/console/test_patient_reads_review_d717.py`.
2. **`GET /studies/{rs}/redcap-link` returned patients' rows** (its last reads: pseudonym, record id, screening
   number, status changes). It is a patient read now (`phi.view`); its page already refused an account without
   patient-level rights.
3. **`GET /studies/{rs}/edc` returned per-subject rows** (record key, visit, date, drafts). It is a patient read now
   (`phi.view` or `monitor.read`).
4. **The console signed a read for a study the account does not see** (an SMO coordinator scoped to another study);
   the claim names no study list, so the orchestrator could not tell. `read_headers` now refuses (403,
   `console.denied`) unless the account sees the study. The reviewer also found that an investigator the study's
   delegation log does not name is signed for: the matrix's `phi.view` cell is `true` for every investigator, and the
   delegation log is the console's own rule on some patient pages (T-309, `Helpers.reads`), not the matrix's.
   Asking it at signing refused pages that show these reads to such an investigator on purpose (the week's SAE
   banner, the set-up page). Left as the matrix says, and put to the owner: should `phi.view` take the delegation
   log for an investigator (`[task:screen, pi]` in the matrix), so that both the console and the orchestrator ask it?
5. **Changing routes still answer with patient data** (`PUT /studies/{rs}/data/{record}` with no values returns the
   record; `POST /studies/{rs}/entry/{record}`; `POST /patients/deceased`): they are in stage `report` (D-483) and
   this card is about reads. The title says GET now; the changing routes are a follow-up, handed to the integrator.
6. **The mail's principal held `phi.view` on every read** (the export, FHIR, the site's set-up, the REDCap
   read-back). It is admitted now only on the reads the mail makes: visits, AEs, subjects, a subject and the
   registry's rows (`tests/unit/test_patient_reads_check_person_and_study.py`).
7. Job records with a CASE job's pseudonym: as said above, the owner's to say.

What did not break it: trailing slash, double slash, encoded and dot segments; HEAD and OPTIONS; the study's case;
a claim for another study, another path or another query; a used claim; `monitor.read` on a route that does not
take it, or without a grant; other service tokens and unlisted principals; the reader bound in one request leaking
into the next or into a new thread.

## Reuse check

`orchestrator.actor.require_actor` and its walk (`walk`, `route_problems`), the console's `assert_for` and
`assert_service`, the test helpers `tests.actor3.signed` / `SignedClient`. Added: the shared list
`tb_common.patient_reads`, the console's `read_headers` / `bind_reader` / `reading_as`, and a signed-read helper
for tests (`OrchBox.read`).

## Dropped (D-311)

No sign-off step.
