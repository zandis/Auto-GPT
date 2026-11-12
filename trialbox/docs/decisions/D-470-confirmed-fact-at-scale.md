# D-470 Stage-12 evidence that settles G1 B1; undated chart facts stay unknown; a section-date suggestion for the owner

- **Task:** G1 bug B1 (`docs/plan/measurements/g1-2026-11-11/BUGS.md`, branch `claude/g1-results-2026-11`)
- **PR:** this branch (`fix/g1-B1-confirmed-fact-at-scale`)
- **Date:** 2026-11-12
- **Status:** proposed (the owner rules on the option in "For the owner"; nothing of it is built)
- **Builds on:** D-135 (a proposed fact only sends a patient to "needs information"; once confirmed it counts),
  D-142 DUMP-01 (an undated record leaves a criterion unknown where the dated ones do not settle it), D-215 (chart
  dates)

## What is known

- G1 (hospital-ja, 50,000 patients, `--model pair`, commit `986d91c`): stage 12 confirmed every chart fact (7 of
  them) and both chart patients stayed "needs". 10000004 should have been ready, and 10000005 should have been
  excluded by its breast cancer. The stub rehearsals proposed 9 facts and passed.
- The patient count does not explain it. The site space has its own lake, built only from its own inputs. On today's
  master the stub passes stage 12 at 500 and 5,000 patients. A 50,000-patient stub run here was killed for lack of
  memory in ingest, before stage 12.
- The difference is the chart reader. G1's chart facts came from the real judge; the rehearsals' came from the stub.
  The run did not keep the facts, only the check's evidence: 7 facts and the patient states. The feasibility counts
  after confirmation (remaining 3, coded 2, confirmed 1) are the same as in the passing stub run, so they do not tell
  the causes apart.

## Two candidate causes (neither shown)

1. **Undated facts.** The prompt (`chart_facts` v2) asks for the date "as written in the chart, empty when the chart
   does not say". A literal reader leaves a lab line under the visit heading, or "乳癌（2019年手術）", without a full
   date. An undated confirmed record leaves the criterion unknown (DUMP-01), so the patient stays "needs".
2. **Dropped demographics.** A reader that leaves out only `birth_date` and `sex` gives exactly 7 facts. 10000004 then
   has no age and stays "needs". This also fits the evidence.

The two can combine. The adversarial review of PR #297 showed that cause 1 alone, fixed by dating facts from the chart
section, still leaves 10000004 "needs" under cause 2.

## Decision (this PR)

- **An undated chart fact stays undated.** No date is taken from the chart around it. A date written near a fact is
  often not its date: a 2010 cancer under a 2026 heading, an unlabelled birth date above a diagnosis, a next-visit date
  on the same line, an old result copied under a new heading. Taking such a date silently turned "needs" into
  "not_eligible" or into "ready" (a silent "no" on an exclusion, which DUMP-01 forbids). "Needs information" is the
  safe state, and it stays.
- **Stage 12 records the evidence that settles the cause.** The check "two pasted charts" lists each chart fact:
  pseudonym prefix, domain, code, day. For each chart patient it also lists the kinds of fact read with their days,
  the kinds missing, and the kinds undated. 10000004's expected kinds are birth_date, sex, gout and urate (its
  "悪性腫瘍なし" is a negation). 10000005's are malignancy, gout and urate. Extra kinds read are counted.
  Structured fields only, no quote or term, synthetic data only.

## What the next G1 run's evidence will show

- `missing` holds `birth_date` / `sex` for 10000004: cause 2.
- `undated` holds the malignancy for 10000005, or the lab / gout for 10000004: cause 1.
- Neither: something else (for example uncoded conditions, shown under `other`), and this record is revised.

## For the owner: an option to rule on (not built)

A section date offered as a **suggestion** on the review list ("date not written in the chart; from the section
heading"). It would become the fact's date only through an explicit correction by the coordinator (Correct, `day`),
never by confirming the fact. It would never be suggested from a line holding a year alone, an era or 民國 year, or a
birth date. The review list would also gain a way to clear a fact's date. Until the owner rules, the coordinator
can already give a date with Correct.

## Not done

- B1 is not fixed. This record and its PR make the next real-model run diagnose it.
- The prompt is unchanged: a new version needs qualification on the pair (D-359).
- No 50,000-patient run on this machine: out of memory in ingest (scale finding F-05).
