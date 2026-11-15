# 19. Model misbehaviour: note reading off, the runs a build touched

**Reader:** Aimedics, with the box owner and the trial team.

*T-609 (review OPS-042). What to do when a model gives wrong note answers: a quote from the wrong patient, a run of
"not met" answers that a person can see are wrong, a canary that suddenly fails, a model update that behaves
differently. Three steps: hold note reading, list what the build touched, release only after a passing canary.*

**Drill:** `test_runbook_19_model_hold` in `tests/unit/test_model_hold.py` (a SCREEN-style evaluation is running; the
hold is set after its first note call; the rest of the note stage asks no model and every note criterion goes to
review; the report on the planted build lists exactly the planted runs and their patients; release is refused until a
canary passes after the hold). Tabletop: once a quarter, the administrator and the PI walk through the steps below
on the DEV box with the stub model.

## What the hold does

The hold is the audited flag `notes.reading` (§15, `/ops/flags`) set to `off`.

| While held | Effect |
| --- | --- |
| Note-stage model calls | none: each note question is answered `unknown` with the reason *not evaluated*, without asking a model |
| Note answers | never exclude a patient; a run whose note stage ends under the hold drops the note answers it got before |
| A running job | stops calling the models within one step (the flag is read before each call, through a five-second cache) |
| Coded filters, lists, mails | keep running; every note criterion is left to a person, and the list says why ("note reading is held") |
| Canary | still runs (admin Models tile, "Run now"; and before each night's model jobs) |

Nothing is restarted and no setting file changes.

## 1. Hold note reading

On the box, from the install folder, as for `doctor` (§4):

```bash
python -m tools.trialbox model hold --reason "wrong quotes on SCREEN of 11-11, ticket 123"
python -m tools.trialbox model status
```

The administrator may instead set `notes.reading` to `off` on `/ops/flags` with the same reason. Either way the change
is one audit event (`flag.set`) with your name and the reason. Tell the PI of each active study that note criteria go
to review until further notice.

## 2. List the runs and patients the build touched

Find the build: the admin Models page shows the serving build of each role, and every gateway answer names it
(`build_sha`). Then:

```bash
python -m tools.trialbox model report --build <sha256, 8 characters or more, or the build id> \
  --from 2026-11-01 --to 2026-11-11 --out deploy/site/model-report-2026-11-11.md
```

Add `--audit-dir` once per audit folder when the gateway writes to a folder of its own; `--json` writes the same
report as JSON. The report lists:

* each run (job) that the build answered for in those days: type, ruleset, state, when, how many model calls;
* each patient whose current candidate-pool row came from such a run (a pseudonym, never a chart number), with the
  criteria the notes decided and the patient's candidate-registry status;
* the build's calls that belong to no run (the canary, the compiler), by label.

The report reads the audit trail and the job tables only; it changes nothing. A patient whose pool row a later run
replaced is listed under that later run only if the later run used the same build.

## 3. Re-review

The PI (or a delegated investigator) re-reviews every listed patient whose note criteria were decided by the build,
first those the run excluded or that the registry shows as contacted or further. The chart numbers come from the
candidate registry export, on the box only. Record the outcome as usual in the candidate registry.

## 4. Fix and release

1. Fix the cause: re-pin the previous build (§5 updates; `tools/pin_model.py`), restart the model server, or wait for
   the vendor's fix.
2. Run the pair canary on the build you will release: admin Models tile, "Run now". Wait until it shows passed.
3. Release:

```bash
python -m tools.trialbox model release --reason "previous build re-pinned, canary passed 11-12 09:10"
```

Release is refused when the last canary failed, checked one model only, is older than `TB_CANARY_MAX_AGE_H` (36 h) or
ran before the hold. Use `--data-dir` when the orchestrator's data folder is not `TB_DATA_DIR`. Setting the flag back
on `/ops/flags` skips that check: use the command.

## Who does what

| Step | Who |
| --- | --- |
| Hold | whoever sees the misbehaviour and has the administrator role or the box shell; tell the administrator |
| Report | the administrator |
| Re-review | the PI of each study, or the investigator the PI delegates |
| Release | the administrator, after the canary |
