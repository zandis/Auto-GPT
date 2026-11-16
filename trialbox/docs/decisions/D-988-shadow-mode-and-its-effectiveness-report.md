# D-988 Shadow mode: the box screens a study unseen, and a report says how its answers compare with the coordinator's

- **Task:** the owner's ruling D-1037 (2026-11-16, #639; `OWNER-RULINGS-2026-11-16.md`, #897). This is the pilot's way to show value. The box screens a shadow study exactly as in production. The coordinator does not see its answers, or sees them only after deciding. The box records its own answer and the coordinator's, and a report compares the two.

  **Date:** 2026-11-16. **Status:** reserved; this is a design, and the build comes after the P1b safety and compiler cards. Lane A2 owns screening, the seal, the answers store and the report. Lane C2 owns the console.

## What exists today (origin/master 9d5853f)

- No study can hide its results. The flags in `tb_common.flags` are global, and a study is `startup`, `open`, `paused` or `closed` (`console/sitestore.py`).
- No record holds a coordinator's answer per patient and criterion. The nearest records are:
  - `excluded_review.crit`, one criterion per patient per job;
  - `orch.feedback.reason_code`, the criterion of a screen fail;
  - `pi_marks` (approach, need_info, not_suitable, not_now).
- The "blinded chart review" in `cascade/certificate.py` is simulated: oracles label a sample. There is no reviewer page and no control against peeking.
- In the model registry, "shadow" is a status for a model build being qualified (D-333). It is unrelated to this card, and the name of this card's setting avoids it: see below.

## Decision

**1. The setting.** A study gets `evaluation: {mode, from, until}` (lane C2 shows it). Mode is one of:
- `off`, the default;
- `hidden`: nothing is shown until the study's evaluation ends;
- `after_decision`: each patient's box answer is shown once the coordinator has decided that patient.

An admin sets it. Each change is the audit event `evaluation.set`, with the old and new values. Changing the mode mid-period ends the period: the report covers whole periods only.

**2. Screening is unchanged.** It uses the same ruleset, cascade, thresholds, models, judged-pair store and schedule. The only differences for a study under evaluation:
- the candidate list is still built, but nothing is delivered: no mail and no export;
- the console's study pages and API routes that return verdicts, tiers, evidence or the list refuse, for every role, while the mode hides them (403, `evaluation_hidden`). The list cards say "under evaluation".

Production behaviour is the thing being measured, so nothing is tuned for the evaluation.

**3. The seal: the box's answers are fixed before any person answers.** At the end of each SCREEN job for a study under evaluation, the box writes its answers to the job's phi outputs as `evaluation-<job>.jsonl`. There is one line per patient: the patient's tier, and each criterion's status, stage and reason.
- The audit event `evaluation.sealed` records the file's sha256 (`output_sha`), the job, the ruleset version and the count.
- The report reads only sealed files, and checks each one's hash against its event. A changed file fails the report; it is not ignored.
- A patient's coordinator answer counts only if it was given after the job that screened that patient was sealed. An earlier answer is reported, not compared.

**4. The coordinator's answer.** A new append-only table `orch.evaluation_answers` holds, per answer:
- study, pid, job;
- level: `patient` or `criterion`, with `crit` for a criterion answer;
- answer:
  - patient level: eligible, not_eligible or unsure;
  - criterion level: met, not_met or unknown;
- `opened_at`: when the coordinator opened that patient's worksheet;
- `answered_at`, `by`, and an optional note.

Rules:
- A correction is a new row with `corrects`. The report uses the first answer and counts corrections separately.
- In `after_decision` mode, the reveal writes `evaluation.revealed` (pid, by, at). A row written after a patient's reveal is marked `after_reveal`, and is never counted as the coordinator's own answer.
- The patient-level answer is required. Criterion answers are required for the criteria the coordinator names as the reason for "not eligible", and are optional for the others. A full grid on every patient would cost the pilot's coordinators more time than the study saves.

**5. The reference: disagreements are adjudicated.** "What each side caught that the other missed" needs a third reading.
- Every patient where the box and the coordinator disagree goes to an adjudication queue, plus a random 10% where they agree, to estimate errors both sides share.
- An investigator who is not that patient's coordinator answers with the two answers shown as "A" and "B". Which side wrote which is assigned per patient by a seeded draw, and stays hidden until the adjudication is written.
- Adjudications are stored in `orch.evaluation_adjudications`, append-only.

**6. The report** is a new scenario, EVAL-REPORT, run on demand or at the period's end. It is aggregate and has no patient rows. Its contents:
- **Agreement:** the share of patients where both answers agree, and Cohen's kappa, at patient level and at criterion level, with 95% intervals (Wilson for shares, bootstrap for kappa) and the counts behind each figure.
- **Time to decision:** the coordinator's median and IQR from `opened_at` to `answered_at`. The box's time per patient comes from the job.
- **Caught and missed** (from the adjudicated patients):
  - eligible patients the box found and the coordinator did not;
  - eligible patients the coordinator found and the box did not;
  - the shares of the agreeing sample that both sides got wrong.
- **Serious misjudgements**, counted and listed by criterion (not by patient):
  - a patient adjudicated eligible whom a side excluded on a hard fail;
  - a patient a side passed who fails a safety exclusion. These are the ruleset's exclusions marked safety, or, if none are marked, every exclusion.
- **Breakdowns:** everything is reported per study and per notes language (D-983's `notes_language` per patient: en, zh-TW, ja, unknown).
- **Small cells:** shown under the FEAS rule (D-18: below the site's small-cell threshold, shown as "<n").
- **Its sentences** are measurements on this site's records. The report makes no claim beyond them and says so: the hospital decides what use it makes of them, and we make no real-data claim.

**7. Who may see what.**

| | During the period | After the period |
|---|---|---|
| Coordinator, investigator | Their own answers only; in `after_decision` mode, the box's answer for a patient once that patient is decided | Everything their roles already allow, plus the report |
| Admin | The setting and the counts of sealed jobs and answers, never answers | The report |
| Steward, privacy | As today (audit and erasure); the steward sees the seals and reveal events, not the answers | As today |

The sealed files and both tables are phi under the existing retention (`settings.retention`), and opt-out erases them (the erasure registry gains the three tables).

**8. How it stays honest**
- The box's answers are fixed and hashed into the audit chain before any person answers (the seal), so they cannot move afterwards.
- The coordinator's answers are append-only and timestamped against the seal and the reveal, so an answer given after peeking is marked, not counted.
- The routes refuse for every role, admin included, so nobody can peek through the console. Reading the database directly remains possible for the box's own operators; the seal makes a changed box answer detectable, though not a read.
- The adjudicator does not know which side said what.
- The report counts and prints every exception: corrections, answers given after a reveal, early answers, patients never answered.

**9. What the console needs (lane C2)**
- the study's evaluation setting (admin);
- the refusals and "under evaluation" cards;
- a worksheet per patient: the patient-level answer, the reason criteria, optional others, `opened_at` taken when it opens;
- the reveal in `after_decision` mode;
- the adjudication queue, with A/B labels;
- the report page.

The console reads the box's answers through one route that applies the visibility rules above. No page reads the sealed files.

## Open for the integrator

1. Whether the worksheet asks for every criterion, or (as proposed) the patient-level answer plus the reason criteria.
2. Whether the agreeing sample for adjudication is 10%, or a fixed number per study.
3. Whether a study may run evaluation and normal screening side by side for different coordinators. Proposed: no; one mode per study per period.
