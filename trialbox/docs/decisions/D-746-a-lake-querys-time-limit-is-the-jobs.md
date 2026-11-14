# D-746 A lake query's time limit is the job's, and a query stopped at it is the lake's limit

- **Task:** NEW-B-45, the first part of T-694 (findings F-29 of `docs/reviews/2026-11-11-scale-timeouts.md`;
  PERF-023 of the 2026-11-12 deep review); placed with lane B2 by the integrator's split of 2026-11-14
- **PR:** this branch (`agent/NEW-B-45-lake-limit-per-job`), on top of NEW-B-41 (#588, D-742)
- **Date:** 2026-11-14
- **Status:** accepted
- **Builds on:** D-675 (the status of a failed lake query: 503 where the lake cannot serve it), D-742 (the lake's
  memory limit met while it opens a snapshot), D-403 / D-490 (a job's pinned lake), OD-10 (no fixed limit unless
  declared with a reason)

## Context

Every lake query had 300 s on the lake and 330 s on the client. The lake's contract takes another value
(`LakeQuery.timeout_s`) and the lake honours it, but no caller sent one. Feasibility and cohort are each one query
over the whole lake; the review measured 300 s crossed at about 140,000 patients. A query stopped at its time limit
came back as the engine's interrupt, a generic error, where the memory limit says `LAKE-LIMIT`.

## Decision

1. **The limit is the job's, per job type:** `TB_LAKE_QUERY_LIMITS`, `TYPE=seconds` by commas, declared with the
   default `FEAS=1800,COHORT=1800` (the time of a query over the whole lake grows with its rows: 140,000 patients
   at 300 s gives about 1,070 s at 500,000; 1,800 s leaves 1.7 times that). A type not listed keeps the lake's 300 s.
   An empty value is the default. A value that is not `TYPE=seconds` once per type, 1 s to a day, is refused, and
   the job fails in words that name the setting (not "internal error"). The real figure for the
   500,000-patient night comes from lane G's capacity measurement (HW-007); the setting takes it without a change.
2. **The job's pinned lake sends it** with every query of the job (`PinnedLake(query_limit_s=…)`, from the job's
   type); a caller may name its own limit for one query; a re-run's lake (`rerun.PinnedLake`) and the library lake
   (`LakeLocal`) pass it on; a stand-in lake without the parameter is still served, and the log says once that its
   queries have the lake's own limit.
3. **The client sends it and waits longer than it** (`READ_MARGIN_S` = 30 s, the margin the client always had), so
   what a caller sees is the lake's answer, not the client's own timeout. Only the read wait follows the limit: the
   connect, write and pool waits stay the client's (330 s). Without a limit the client is as before.
4. **A query stopped at its time limit is the lake's limit:** `LakeTimeLimitError` (a `LakeLimitError`), 503,
   "LAKE-TIME: the lake query was stopped at its time limit of N s …" naming the setting. An interrupt that was not
   the timer's stays what it was. A limit of 0, below or above a day (`MAX_QUERY_LIMIT_S`: a timer beyond
   `threading.TIMEOUT_MAX` never fires) is refused as the caller's fault (`LakeSaid`, 422).
5. **The job's failure says it:** a job that fails on the lake's time or memory limit shows the lake's own sentence
   (`LAKE-TIME`, `LAKE-LIMIT`, written by the lake, no value of a row) after `HTTP 503` in its detail; any other
   failure of the lake keeps `HTTP <status>` (D-557).

## What a person sees differently

A feasibility or cohort job on a large hospital is no longer stopped at 300 s. A query that runs past its limit says
so (`LAKE-TIME`, 503) in the job's failure, where it said the engine's interrupt.

## Not in this card (the rest of T-694)

Patients as a join instead of a list (`list_contains` over every scoped patient), the cascade's note stage in batches,
excluded patients streamed to the store, the compiler's equivalence sample in SQL: proposed to the integrator as
their own cards (most are in other lanes' files).

## Tests

`tests/unit/test_lake_query_limit_per_job.py` (12 tests; all fail on the parent): a real lake stops a query at a
one-second limit with `LakeTimeLimitError` and serves the next query; through the real service and client, 503 with
`LakeTimeLimitError: LAKE-TIME`; the client sends the limit and waits the limit plus the margin, and sends none when
none is asked; the setting per type, its default and its refusals; a job's queries carry its limit, a caller's own
limit wins, a stand-in without the parameter is served; an empty setting keeps the default, duplicates, full-width
digits and more than a day are refused; the client keeps its connect, write and pool waits; the lake refuses a limit
of 0, below or above a day (422); a re-run and the library lake pass the limit on; a job's failure says LAKE-TIME;
a real FEAS job through the orchestrator sends 1,800 s, and with a setting that cannot be read fails naming it. No
state change.

## Review

One adversarial read-only review by a fresh agent (the job paths, the client's waits, the store's timer, the
setting's edge cases, the night's rebuild and holds, seven mutants). Findings, fixed test-first in the second
commit: a re-run of a FEAS or COHORT job dropped the limit (the re-run's lake took no limit); LAKE-TIME never reached
the job's failure (the record said it did); a setting that could not be read failed every job as "internal error";
an empty value turned the default off; the per-request wait also stretched the connect, write and pool waits to the
limit; no bound on the limit (0, negative, or beyond the timer's maximum); duplicates and full-width digits accepted;
a stand-in that dropped the limit said nothing; the wiring into a real job was untested. Seen, not changed: the
criteria compiler's own lake client keeps 300 s (its queries are not job queries); a timer firing just after a query
ends meets a closed connection, as before.
