# The launch sheet for the confirming launch, 2026-11-17 (card H-7)

**Reader:** the integrator, who launches; and the people who build TrialBox

This page is what to type, what to check first for free, what it should cost, and what to read afterwards to decide
each of the three targets of `docs/plan/42-plan-2026-11-16.md`, section 3. Lane H launched nothing and spent
nothing. Every command below marked "run here" was run on master `fae5c1f7` (train 65) in a container with no
cloud access. A target is met only by a launch (D-1064).

## 1. What differs from launch P1b

| P1b's fault | Now |
| --- | --- |
| The filter `G2TCGA-BRCA` under tag `m2` matched no protocol, so tcga was not scored | The filter is checked before anything starts: an id that is not one of its set's ids is refused, and the refusal lists the ids (D1) |
| Step `07g-gate` polled an unreadable `GET /models` for 1,500 s | Fixed, not skipped: the step reads with the service token, ends in seconds when the gate is open, fails at once on 401 or 403, waits at most 480 s, and a closed gate stops the run (D2) |
| One protocol in flight, GPU mean 22 % | Three in flight for a compile-bound set (sigir) by default; the report says how many were in flight (D7) |
| The source bundle was shallow and the clone failed on the VM (P1a) | The bundle is proved before it is uploaded, by cloning it as the VM does; a build or dev launch is refused without `--src-bundle` (D8) |
| A protocol in flight at the deadline was marked as a FEAS timeout | No protocol starts with less than `--acc-min-start` (600 s) of its set's budget left; a cut is `not_run_time_budget` and a resume picks it up (D4) |
| `--resume` dropped the tag | `--resume` keeps the launch's `--acc-rs-tag` (D3) |

## 2. The ids, under the tag

The box keeps a ruleset under its id. If the VM's disk still holds P1b's rulesets (tag `m2`), use a new tag. This
sheet uses `m3`. An id is the set's letter, the tag, then the name. List them; do not type one from memory.

Run here:

```
PYTHONPATH=libs:services:. .venv/bin/python -m tools.box_run acc-ids --only jmed,tcga,sigir --rs-tag m3
```

It printed:

- **jmed** (prefix `Mm3`): `Mm3JMED-DM`, `Mm3JMED-HT`.
- **tcga** (prefix `Gm3`): `Gm3TCGA-BRCA`, `Gm3TCGA-COAD`, `Gm3TCGA-HNSC`, `Gm3TCGA-KIRC`, `Gm3TCGA-LIHC`,
  `Gm3TCGA-LUAD`, `Gm3TCGA-LUSC`, `Gm3TCGA-PRAD`, `Gm3TCGA-THCA`, `Gm3TCGA-UCEC`.
- **sigir** (prefix `Sm3`): "not known here: the sample is drawn from the set's source files, not in the local
  cache". Pass no `--acc-protocols` for sigir: an id typed for sigir cannot be checked before the VM starts.

## 3. The source bundle

In a full clone (not a shallow one) at the launch commit:

```
PYTHONPATH=libs:services:. .venv/bin/python -m tools.box_run src-bundle --commit <full 40-character sha> --out /path/src.bundle
```

It is refused in a shallow checkout and with a short sha. It ends by cloning the bundle into a temporary folder
with a plain `git clone` and checking the commit out, which is what the VM's step `b01-source` does.

## 4. The command line

The sets run in the order given, cheapest first. The first set is the gate set: it must answer at least one
patient or the run stops (hand-over, section 8).

```
deploy/gcp/box-run.sh --mode validation --steps dev,acc \
  --release-id dev-<commit12> --commit <full sha> --src-bundle /path/src.bundle \
  --only jmed:300,tcga:500,sigir --acc-rs-tag m3 \
  --acc-protocols "tcga:Gm3TCGA-BRCA" --acc-streams "sigir:3" \
  --acc-deadline "jmed:<s> tcga:<s> sigir:<s>" --skip 08-qualify --no-wait
```

- `--acc-streams "sigir:3"` is already the default; naming it shows in the preflight. jmed and tcga run one
  protocol in flight (they are not compile-bound; tcga BRCA is one protocol).
- `--skip 08-qualify` is as on P1b (left out, said, never a pass). The qualification record is its own run
  (plan 42, section 4b).
- The sizes `jmed:300` and `tcga:500` are the hand-over's (section 4.8). The record of P1b on #639 does not state
  the `--only` it used; use P1b's own line if it differs.
- The run no longer sets `TB_SCREEN_MAX_PAIRS` (D-953 is on master). If the disk's `deploy/.env` still has it from
  an earlier run, it stays, and the run records it; remove it by hand before the launch.

## 5. The free checks, in this order, and what each must print

1. **The ids** (section 2). Must list `Gm3TCGA-BRCA`; `"refused": []`.
2. **The estimate.** `deploy/gcp/box-run.sh --estimate --mode validation --steps dev,acc --only jmed:300,tcga:500,sigir`.
   Prints the low and high bound and their sources. Post it on #639 with the worst case and the running total
   before the start (D-505).
3. **The preflight**, with the launch's own options and `--preflight` added after `box-run.sh`. No cloud call, no
   credentials, no `TB_BUCKET`. Run here with the line of section 4 (without the bundle, which this shallow
   container cannot make), it printed:

   ```
   validation-check: a VALIDATION box can route the run's calls
   preflight: ok     the steps are known
   preflight: ok     the launch's options would hold on the VM (filter, tag, streams, budgets, commit)
   preflight: ok     protocols in flight per set (D7: 3 for a compile-bound set unless --acc-streams): {'jmed': 1, 'tcga': 1, 'sigir': 3}
   preflight: FAILED the source bundle is proved (D8): --src-bundle FILE is needed: ...
   preflight: ok     the metadata builds (every key the steps need, no key-like value)
   ```

   With the proved bundle every line must read `ok` and the exit code must be 0. Exit 2 is the filter, 6 the
   preflight, 9 a blocker of the validation-check.
4. **The wrong id, once, to see the refusal.** With `--acc-protocols "tcga:G3TCGA-BRCA"` it stopped with exit 2:
   "tcga: G3TCGA-BRCA not among its ids (prefix 'Gm3'; ids Gm3TCGA-BRCA, ...)" and "refused (no VM started)".

The paid launch is the same line without `--preflight`. It runs the same checks first and refuses before anything
is uploaded or started.

## 6. Hours and US$

US$2.74 a VM hour, spot (the hand-over's constant). The disk and the bucket are not in these figures.

**Measured inputs.**

| Input | Figure | Source |
| --- | --- | --- |
| Launch P1b, whole | 3.38 h, US$9.26 | #639, 2026-11-16 11:18 UTC |
| P1b, sigir | its 9,000 s budget used; 93 protocols attempted, about 97 s each, one in flight | the same |
| P1b, the idle gate step | 1,500 s | the same |
| tcga BRCA, 500 patients | 1,352 s (1,014 model calls) | hand-over, section 4.8, on `1157c9bf` |
| The canary through the gate | about 3 to 4 minutes when the gate must restart | hand-over, section 4.6 |

**Derived, not measured.** P1b less its sigir budget (2.50 h) and its idle gate (0.42 h) leaves about 0.46 h for
everything else it did: the dev bring-up, the data, the ingest and jmed.

| | Low | High |
| --- | --- | --- |
| Bring-up, data, ingest, jmed (P1b's remainder) | 0.46 h | 0.46 h |
| The gate step | 0.02 h (open) | 0.13 h (480 s) |
| tcga BRCA | 0.38 h | 0.38 h |
| sigir, 103 protocols at 97 s | 0.93 h (three in flight, the GPU keeps up) | 2.78 h (no gain over one in flight) |
| **Total** | **about 1.8 h, US$4.9** | **about 3.75 h, US$10.3** |

**The driver's own estimate**, run here (`--estimate` with the sets of section 4; it does not read `--skip`, so it
lists qualify as unmeasured):

```
  jmed: JMED-Personas, 300 patients x 2 criteria (ja)                  0-540
  tcga: TCGA-Reports, 500 reports x 10 cancer-type criteria          72-2304
  sigir: SIGIR, physician criterion labels (1,015 criteria, ...     684-3708
  b01-b03 clone, venv, images (this VM, 2026-11-15)                      198
  02 the stack up by the direct route (this VM, 2026-11-15)              281
  03-07 env, pins, serving record, G-1, canary                           260
  08 trialbox eval qualify --box (full)                              unknown
  known part 0.42 to 2.03 h (US$1.14 to US$5.55 spot); 2 step(s) unmeasured, bounded by the cap: 6 h = US$16.44 spot
```

- The two estimates disagree at the top. The driver's high for sigir (3,708 s) is from the plan's call counts; P1b
  used all of 9,000 s with one in flight. The table above is the more careful high bound; the worst case is the
  cap, 6 h and US$16.44, which the VM enforces itself.
- Its tcga line is for all ten protocols; the filter of section 4 runs BRCA alone.
- Three in flight has never been measured. The low figure assumes the full gain, the high figure none.
- Lane A2's fixes change how many protocols reach SCREEN. On P1b 30 of 93 failed early and cost less than a
  screened protocol; if more now screen, sigir takes longer than the low figure.
- `--acc-deadline`: a set stops starting protocols 600 s before its budget ends. The budgets are the integrator's
  to set with the estimate; the high column above is the time each set needs if nothing is faster than measured.
- The owner's rule: stop a launch more than 50 % over its estimate. The cap is US$200; the running total was
  "about US$113.08 at most" before the last small VM (#639, 2026-11-17 00:35 UTC).

## 7. What to read in the results

After the run: `deploy/gcp/box-run.sh --collect <run id>` fetches each finished set and scores it here, free. Each
set's score is `acc/<set>/score.json`; the run's summary is `acc-score.json`. Then:

```
python -m tools.public_accuracy.replay <the collected run folder> --json report.json
```

Every score names its answer key (`answer_key`). A new launch builds key v2 (D-1104).

| Target | Where | What decides it |
| --- | --- | --- |
| 1. No eligible patient excluded, on the corrected key | sigir and jmed `score.json`, block `pairs`: `eligible_lost` (k of n), with its `denominators`; and `unjudged_exclusions` | k must be 0 on key v2 without the conflicted pairs (D-1064). Beside it, read the figure with them and the conflicted pairs by id; card H-6 adds those fields. Read `eligible_lost_on_the_line_the_criterion_labels_exclude` for any pair lost on a line the physicians' own labels exclude, and `unjudged_exclusions` for exclusions on lines no gold row judges (the placed age lines) |
| 2. The pathology figure | tcga `score.json`, block `pathology` | `scored` must be true. `ineligible_excluded`, `wrong_exclusions` and `eligible_lost` are the three numbers of the sentence in `figure`. PoC-1's claim on `b266f9b7` is 384 of 450 excluded, 0 wrong exclusions, 0 of 50 eligible lost, on 500 reports. "Not scored" names its reason and is never a pass |
| 3. Fewer than one protocol in ten failing before SCREEN | sigir `score.json`, block `protocols` | `attempted`, `failed_before_screen_share`, `failed_share` (before or in SCREEN) and `failed_by_class`. Budget cuts (`not_run_time_budget`) are listed apart and are not failures. The boolean `fewer_than_one_in_ten_failed` counts failures before or in SCREEN; which of the two shares is the target is an open question to the integrator (#639, the H-3 line) |

Also read, before believing any figure:

- **The report's accuracy line**: "protocols in flight: N at most of S". For sigir N should be 3.
- **`07g-gate`** in the run's steps: seconds, and the gate open. `TB-GATE-CLOSED` or `TB-GATE-REFUSED` stops the
  run by design.
- **`save_give_ups`** in a set's result: a save the driver gave up on is now said, not silent (D6).
- **The set's `protocols.in_set` against `in_answers`**: a protocol missing from `answers.json` is counted, not
  dropped.

## 8. If it stops

- A pre-emption or a budget cut: `deploy/gcp/box-run.sh --resume <run id>`. Finished steps and finished protocols
  are kept; the tag is kept.
- A refusal with exit 2, 6 or 9 cost nothing: no VM was started.
- A stop on the VM leaves the last checkpoint (`acc-partial/<set>.tgz`), which the replay reads like a finished
  set and labels by what it holds.
