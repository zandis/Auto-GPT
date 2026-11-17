# The judged-pair store in launch P1b, read offline, 2026-11-17 (card H-16, D-1126)

**Reader:** the people who build TrialBox, and the integrator costing the confirming launch

This page reports what the judged-pair store (lane A2's D-908, the owner's D-519) did in launch P1b, and what a
second run of the same sets on the same box would save. It was read from P1b's stored sets (run
`box-20261116T074927Z-3b2f5e38`, commit `3b2f5e38`; branch `integrator/p1b-artefacts`, `sigir.tgz` and `jmed.tgz`)
by the code of lane H's branch `claude/lane-h-16-pair-store-hits`, cut from master `8f5d429c`. No model, GPU or
network was used. The tool:

```
python -m tools.public_accuracy.pair_store sigir.tgz jmed.tgz --json report.json
```

## Was the store there and on in P1b?

Yes. Commit `3b2f5e38` is master at train 44 merged into lane G's driver, and the store landed in train 43. Every
SCREEN report the run stored has the store's block, and every one says `on: true`: 63 of 63 for sigir, 2 of 2 for
jmed. The services log names no store fault.

## (a) What the run recorded

| Set | Read from the store | Asked of a model | Hit rate | Pairs judged (S3, S4) |
| --- | --- | --- | --- | --- |
| sigir | 0 | 161 | 0 of 161 | 141, 0 |
| jmed | 0 | 889 | 0 of 889 | 560, 130 |
| all | 0 | 1,050 | 0 of 1,050 | 701, 130 |

The traces agree with the store's own count, job by job. They hold 171 note-question calls for sigir: 168 questions
and 3 schema repairs. For jmed they hold 897: 889 questions and 8 repairs. In 64 of the 65 jobs with a report, the
traced questions equal the store's `read + live`.

The one exception is a sigir job whose report says 1 live and which has no trace under its job id. One trace in
the stored sigir file has a job id whose tail was masked when the file was stored (`[ID_NUMBER]`). Its first ten
characters are this job's. The tool does not join them by guess, so it prints that one job as "differs" and counts
the masked trace as a job with no report. The other sigir job with traces and no report failed in judging: its 7
questions are not in the store's count. So 168 traced questions, less those 7, give the 161 live the reports count.

A hit rate of 0 is what this run could give. No question was asked twice: not within a job, and not across jobs
(see (c)). The box had not answered these questions before at this index date and build.

## (b) What a second run of the same sets on the same box would save

The second run is the same sets on the same box. It needs the same build, prompt, snapshot (2026-11-15) and
**index date (2026-11-16)**. Every question would be found again, except the first question of each model in each
job: a model that has not answered live in a job reads nothing (D-908).

| Set | Questions found again | Gateway calls saved | Still asked live | Time saved (estimate) | US$ at US$2.74 a VM hour (estimate) |
| --- | --- | --- | --- | --- | --- |
| sigir | 104 of 168 (61.9%) | 106 | 64 | about 176 s | 0.13 |
| jmed | 885 of 889 (99.6%) | 893 | 4 | about 136 s | 0.10 |
| all | 989 of 1,057 (93.6%) | 999 | 68 | about 312 s (5.2 min) | 0.24 |

- **sigir saves less** because its 48 judging jobs are small: 14 of them ask a single question, and that question is
  the first of its model in the job.
- **The time is an estimate**, not a measurement. Each trace holds one timestamp and no duration, so the seconds of
  one call are not measured. The figure is each job's span of note-question traces (first to last), divided by its
  questions, times the questions it would save. For jmed that is about 0.15 s a question, with several calls in
  flight. Each jmed job's span (66 s and 71 s) is just under its recorded wall time (69 s and 74 s).
- **The questions are told apart by part of the store's key.** That part is the model, the build, the served prompt
  and the question as the models saw it. The question is `matching.cascade.judge.question_digest` over the traced
  input: the criterion's wording, the note question, the index date and the excerpts. A run on another day has
  another index date, so it would find none of them.

## (c) The same question asked twice in one run

None, in either set: no repeat within a job and none across jobs.

## (d) What the records could not tell

- **The store's own key** (`JudgedPairs.key`) cannot be computed from P1b's records. Four of its parts change from
  question to question and are not recorded:
  - the patient's pseudonym;
  - the criterion's canonical hash;
  - the criterion's window;
  - the cascade's role (S3 or S4). Every SCREEN note call is labelled `s3_note_judgement` by `tb_llm/v1_roles.yaml`,
    S4 included.

  The prompt id as called, the prompt file's sha, the schema and the note mask version are not recorded either, but
  one commit and build fix them. The tool calls `JudgedPairs.key` itself only when a trace carries the cascade's
  question (`tb.asking`); no record of the product writes that today.
- **The seconds of one model call:** not measured (see (b)).
- **The gateway audit** counts the whole box since the set began (`judge@5`: 6,717 since 08:40:28 for sigir and
  6,572 since 08:36:27 for jmed). It is not either set's own count, and the tool does not use it.
- **One traced job id** in the stored sigir file is masked (see (a)), so its one question cannot be tied to its
  report by the record alone.
- `answers.json` holds no job metrics. The job's `llm_calls` and `wall_seconds` are in `progress.json`
  (`screen_metrics`).

## Limits

- A second run's saving holds only on the same box, build, prompt version, snapshot and index date, with no patient
  opted out between the runs, and with the store's retention keeping the snapshot.
- "Still asked live" is a floor. With several calls in flight, more than one question of a model can be asked
  before its first answer names the build.
- An S3 and an S4 question about the same note would look like one question to the tool. That is because the S3 or
  S4 role is not traced. P1b had no such pair: the tool found no question twice at all.
