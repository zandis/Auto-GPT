# Launch P3 on paper, 2026-11-17 (card H-27)

**Reader:** the integrator, who launches only on the owner's yes; and the lanes that own what this page finds

This page plans launch P3: the confirming launch again, on the master that holds #996 (an exclusion never excludes on
an age or a sex alone when its line names more) and #997 (the sentinel quote date is no date on SCREEN's judge path).
It says which sets run and how large, the index day, how every figure is printed, what P3 must show that P2b did not,
the pathology question, the estimate and its stop line, the launch line, and what is not ready. Nothing was launched
and nothing was spent. No cloud call, model or GPU was used.

Every command below was run on master `3f6a02ecc703582667ad2027233043f870ca8790` (train 75), from `trialbox/`, in a
container with no cloud access, unless it says otherwise. P2b's stored sets were read from branch
`integrator/p2b-artefacts` (folder `trialbox/.p2b-artefacts/`) in a detached worktree; nothing from that branch is
copied here beyond the figures quoted. The data is public (SIGIR 2016 through NCBI TrialGPT, JMED-Personas CC BY 4.0,
TCGA-Reports CC BY 4.0).

**No figure on this page meets a target.** A target is met only by a launch (D-1064 item 4). "Within the target"
says whether a launch is worth its cost. Each finding says whether it is **shown** (read from a record or the code,
or printed by a command run here) or a **hypothesis**.

## 1. P3 in brief

| Item | Plan | Section |
| --- | --- | --- |
| Commit | master at the launch, at least `3f6a02ec` (it holds #996 as `0ee24331` and #997 as `f549bfb8`) | 5 |
| Sets and sizes | as P2b: `jmed:300`, `tcga:500` with BRCA alone, `sigir` (its 104 protocols); trec2023 does not join | 2 |
| Tag | `m4` | 2 |
| Index day | the box's day at step `53-acc-data` (`acc_ref`): the launch day in the box's zone; it must not be 2026-11-17 | 3 |
| Printing | every target-1 figure three ways: as stored; without D-1064's six; without the six and the age-line class | 4 |
| Estimate | 2.5 VM hours, US$6.9; high 3.66 h, US$10.0 | 7 |
| Stop line | US$10.3 (1.5 times the estimate; the owner's rule) | 7 |
| Worst case | the launch's cap, 6 h, US$16.44 | 7 |
| Money | about US$132 of US$200 spent before P3; about US$61 left after it at the estimate | 7 |
| Ready today | the free checks pass (exit 0). Three rulings decide whether P3 can show targets 1 and 2 within at all | 9 |

## 2. Sets, sizes and tag

**The same sets and sizes as P2b.** P3 confirms what changed since P2b. The same sample makes the two runs
comparable pair by pair and report by report.

| Set | P2b (source) | P3 | Why |
| --- | --- | --- | --- |
| jmed | 300 patients, 2 protocols, budget 3,600 s, used 117.6 s (`jmed.tgz`, `work/set-clock.json`) | `jmed:300`, budget 3,600 s | the same 330 eligible pairs |
| tcga | 500 reports, BRCA alone, budget 2,400 s, used 374.5 s (`tcga.tgz`, `work/set-clock.json`; `work/answers.json` holds one ruleset, `Gm3TCGA-BRCA`) | `tcga:500`, filter `tcga:Gm4TCGA-BRCA`, budget 2,400 s | target 2 is BRCA's figure |
| sigir | 104 protocols, 3 in flight, budget 7,200 s, used 6,728.1 s (`sigir.tgz`, `work/set-clock.json`; `work/answers.json` 104 rulesets) | `sigir`, 3 in flight, budget 10,800 s | P2b used 93 % of its budget; see section 7 |

- **The same sample (shown in part).** The tcga sample is drawn with a fixed seed (`tools/public_accuracy/sets.py`,
  `SEED = 20261114`). P2b's `built/gold/ids.json` for tcga has sha256 `711e3756fac788a7...`. P3's should be equal; if
  it is not, the per-report comparison of section 6 compares different reports, and the page reading P3 must say so.
- **The tag `m4` (shown).** An id is the set's letter, the tag, then the name (`acc-ids` below). P2b used `m3`.
  The integrator gave `m4` to trec2023 (H-12's answers). Sets of different letters cannot collide: P3's ids are
  `Mm4...`, `Gm4...` and `Sm4...`, trec2023's would be `Um4...`. So P3 and a later trec2023 launch can both use
  `m4`.

**trec2023 does not join P3 (recommendation).** H-12 recommended trec2023 after the confirming launch, once sigir's
rate at three in flight on master was measured. P2b measured it. Derived from it, not measured:

| | Figure | Source |
| --- | --- | --- |
| sigir, 3 in flight (P2b) | 6,728.1 s for 104 protocols: 64.7 s a protocol | `sigir.tgz`, `work/set-clock.json` `used_s`; `work/answers.json` |
| sigir, 1 in flight (P1b) | 96.5 s a protocol | `trec2023-plan-2026-11-17.md`, section 2 (P1b's `box-calls.log`) |
| The gain of three in flight | 96.5 / 64.7 = 1.49 times (two commits apart, so not the streams alone) | derived |
| trec2023, 297 protocols at 114.3 s / 1.49 | 22,783 s, 6.33 h for the set | derived from H-12's rate on `1157c9bf` |
| The same with H-12's slowdown (x 1.185) | 27,000 s, 7.50 h for the set | derived |

- Joined to P3, trec2023 would make a launch of about 8.7 to 9.9 hours. That is more than this launch's 6 h cap, so
  it needs a resume, and it costs about four times P3.
- trec2023 decides no target of plan 42 section 3. Its pairs would join target 1's denominator and change what the
  figure means.
- Its licence row is "permission-to-ask", and its trial texts are live records, not the judged snapshot (H-12,
  section 3).
- Its own launch, after P3, can use the table above: about 6.9 to 8.5 VM hours with the fixed steps (US$18.8 to
  US$23.3), which may not fit one 8 h cap at the high end. That is H-12's plan to update, not this page's.

## 3. The index day, and level (b) from the stored sets

**What the day is (shown).** The driver fixes the build day once per run and keeps it in the run's state: `acc_today`
in `deploy/gcp/box-install-run.sh` sets `acc_ref` to the box's date in its `TB_TZ` (else UTC) at step `53-acc-data`.
Every set is built with `--ref` on that day, and the snapshot is the day before (`step_acc_ingest`). The index day
SCREEN uses is the same day: H-18 showed five records agree on 2026-11-17 for P2b (`p2b-review-2026-11-17.md`,
section 4).

**P3's day.** The launch day in the box's zone. It must **not** be 2026-11-17:

- The judged-pair store (D-908, D-1126) keys a question by the index date, among other parts
  (`services/orchestrator/judged_store.py`, `JudgedPairs.key`). On P2b's day, a question asked again under the same
  build and prompt could be read from the store and not asked. P3's tcga figure would then partly be P2b's answers
  again, not a second sample. Whether the store survives between launches on this VM is a **hypothesis**; P2b's
  reports read 0 from it (`work/screen/Gm3TCGA-BRCA.json`, `cascade.judged_store.read` 0; the same in every sigir and
  jmed report).
- After the run, every SCREEN report's `cascade.judged_store.read` must be 0. A read above 0 is said beside the
  figure.

**What level (b) needs, and what is missing (shown).**

| Piece | On master today | Without it | Card |
| --- | --- | --- | --- |
| The day in the stored set | No. `work/set-clock.json` holds `used_s`, `deadline_s` and, since H-14, `tz` (`deploy/gcp/box_vm.py`); `acc_ref` stays in the VM's state | the operator passes the day by hand | P3-H2 |
| The replay reads it | No. `replay.identify` takes the build day from `eval/public_accuracy_key/MANIFEST.json` only, which pins P1b's key v1 | "Level (b) was not run: the run's record names no index day" (P2b's `replay.txt`) | P3-H2 |
| A stored coded verdict on a line the re-compile no longer codes | Kept as stored (`tools/public_accuracy/rerun.py`, `rescreen`: `basis == "coded"` gives the stored verdict) | level (b) cannot show #996's effect (section 5) | P3-H3 |
| Stored judge replies read through the box's path | No. `rerun.judge_replies` uses `GatewayJudge`, not `tb_common.llm` | target 3's level (b) is not to be read (H-18, section 3) | H-18's card, still open |

None of these blocks the launch. Until P3-H2 lands, level (b) runs from the stored sets with the day given by hand,
read first from the SCREEN reports:

```
python -m tools.public_accuracy.replay sigir.tgz jmed.tgz tcga.tgz --index-day <D> --build-day <D> --json replay-b.json
```

where `<D>` is every SCREEN report's `run_date` (`work/screen/*.json`), which must be one day. This is how H-18 ran
P2b's level (b).

## 4. Every figure three ways

The integrator's ruling of 2026-11-17 10:32 UTC (quoted in `p2b-review-2026-11-17.md`, section 1): every target-1
figure is printed three ways, as stored; without D-1064's six conflicted pairs; without the six and without the class
"excluded on an age line the patient's own text contradicts the label on". Targets 2 and 3 read no gold pair, so their
three figures are equal; they are printed once and said to be equal.

| Column | Who prints it today (shown) |
| --- | --- |
| As stored (with the six) | `tools.public_accuracy.replay`: `targets.eligible_wrongly_excluded.<level>.v2.with_conflicted`. The scorer on master: `pairs.<lang>.eligible_lost` in `score.json`. P2b's own `acc-score.json` was scored before H-6 (train 69) and has `eligible_lost` only |
| Without the six | The replay: `numerator` over `denominator` of the same block. The scorer on master: `eligible_lost_without_conflicted` (D-1118). `tools.box_run acc-score` carries `conflicted` in its summary |
| Without the six and the age-line class | **No tool.** H-18 subtracted the class's 2 pairs by hand from `trace.json`. `tools.public_accuracy.trace` lists the rows but does not mark the class |

So the third column needs a card (P3-H1, section 10). The class is a ruling over two named pairs; the card must turn
it into a rule the tool can apply (a pair labelled eligible, excluded on a line whose only logic is an age, where the
age the key itself gives the patient fails that line) and name each pair it marks, never relabelling one. Until it
lands, the reader of P3 subtracts by hand from `trace.json`, as H-18 did.

## 5. What P3 must show that P2b did not

P2b's figures are at replay level (a), key v2 (`replay.json` on the artefacts branch; `p2b-review-2026-11-17.md`).
The changes since `57263236` are read from `git log 57263236..3f6a02ec`.

### Target 1: no eligible patient wrongly excluded

| | As stored | Without the six | Without the six and the age-line class |
| --- | --- | --- | --- |
| P2b, level (a) | 5 of 424 (sigir 5 of 44) | 4 of 420 (sigir 4 of 40) | 2 of 418 (sigir 2 of 38) |
| P3 if each change does what it should (hypothesis) | 4 + k of 426 (k is 0 to 2) | 3 of 420 | 1 of 418 |
| Within the target | 0 of n | 0 of n | 0 of n |
| Not confirmed | any pair excluded beyond the named ones; or sigir-20156 x NCT01227499 still excluded | the same | the same |

How the P3 row is reached, pair by pair:

| Pair (sigir) | P2b | Change on master since `57263236` | P3, expected |
| --- | --- | --- | --- |
| sigir-20156 x NCT01227499, EXC-04 "women with pregnant or lactation" | excluded at S1 on `sex` female alone | #996 (`0ee24331`, D-954): such an exclusion is flagged `qualifier_dropped`; a mixed line goes to the notes | not excluded (hypothesis: it needs the fresh extraction to name pregnancy or lactation again) |
| sigir-201422 x NCT00236912, INC-04 "Aged 18 years or older" (the benchmark wrote it) | excluded at S1 | none | excluded; the age-line class |
| sigir-201422 x NCT00674726, INC-03 "older than 15 years" | excluded at S1 (`age.min` 16) | none; the ruling: whole completed years, `age.min` 16 is right | excluded; the age-line class |
| sigir-20154 x NCT01701453, INC-06 "Target lesion(s) must be amenable..." | excluded at S3, both models, verified quote | none; lane A2 proposes "conflicted", not ruled | excluded |
| sigir-20142 x NCT00711399 (conflicted) | excluded on the line the labels exclude | none | excluded; in the first column only |
| sigir-201425 x NCT00282269 and sigir-201429 x NCT00703417 (both conflicted) | not answered: their protocols failed in screen judging | #997 (`f549bfb8`, D-958) | answered: the first column's denominator grows by 2 (424 to 426), and k (0 to 2) is how many of them P3 excludes. Each one excluded on a line their labels do not exclude on is a finding to trace (D-1118) |

- **#996 on P2b's own stored reply (shown).** Re-compiled offline from P2b's stored `ir_extract` replies with
  `rerun.recompile` on master, `SM3NCT01227499-EXC-04` comes out class `note`, flags `needs_review`,
  `qualifier_dropped`, with no coded sex; `SM3NCT00997100-EXC-21` the same. So on P2b's own reply the change does what
  it should. P3 asks the model again, so the reply can differ.
- **#996 does not catch every such line (shown).** `SM3NCT01863628-EXC-06` "in pregnancy and lactation;" re-compiles
  as `structured`, logic `sex: female` alone, flags `needs_review`, `stray_field` (also its stored draft in
  `answers.json`). Its reply names no other concept, so the new rule does not fire, and every woman on that protocol
  is still excluded at S1. Its only gold pair is a "would consider" woman, so target 1 does not move. A card for lane
  A2 (P3-A1).
- **Level (b) on master still prints 4 of 420 (shown).** `replay --index-day 2026-11-17 --build-day 2026-11-17` on
  P2b's three sets with master's code: level (b) v2 4 of 420, 5 of 424 with the conflicted pairs. The re-compile moves
  EXC-04 to the notes, but `rerun.rescreen` keeps the stored coded "fail" of a line it can no longer decide. That is a
  fault in lane H's replay (P3-H3), not evidence that #996 fails.
- **Within the target needs a ruling, not only a launch (shown by the table).** If every change works, P3 still
  excludes sigir-20154 x NCT01701453 and the two age-line pairs. The box's answer on INC-06 is the plain reading,
  with a verified quote and both models agreeing (H-18, section 1). So the second column cannot be 0 unless the
  owner sets the age-line class aside and the integrator rules on INC-06, or the models answer differently.
- jmed's 0 of 330 is not evidence that no jmed patient would be lost: P2b's jmed asked no note question, because its
  condition lines compile `structured` (H-18's card for lane A2, still open on master).

### Target 2: the pathology figure

| | Figure |
| --- | --- |
| P2b, level (a) | excluded 379 of 450, 0 wrong, 0 of 50 lost (`replay.json`, `targets.pathology.run`) |
| Change on master since `57263236` that should move it | none shown. #997 changes the one tcga reply that carried a sentinel date: the judge's "unknown" with `quote_date` "0000-01-01", corrected once and answered again (`tcga.tgz`, `work/raw-traces.json`: 3 sentinel dates, 1 schema correction). Under #997 the first reply is taken as "unknown": the same verdict, one call fewer |
| Within the target as coded today | exactly 384 of 450, 0 wrong, 0 of 50 lost (`replay.py`, `within_target` compares the tuple for equality) |
| Not confirmed | any wrong exclusion or any eligible report lost; a figure outside the tolerance the integrator rules (section 6) |

### Target 3: fewer than one protocol in ten failing

| | Figure |
| --- | --- |
| P2b, level (a) | 3 of 107 failed (2.8 %), all in screen judging; 0 before SCREEN (`replay.json`, `targets.protocols_failing.a`) |
| Change on master that should move it | #997 (`f549bfb8`): `no_sentinel_date` runs in `tb_common.llm` on every reply with a `quote_date`. Its test holds one of the three stored replies (`tests/unit/test_sentinel_date_on_screens_path.py`) |
| P3, expected (hypothesis) | 0 of 107 failing in screen judging on a sentinel date; sigir's traces held 19 schema corrections and 57 sentinel dates in P2b (`sigir.tgz`, `work/raw-traces.json`), which P3 should not repeat |
| Within the target | at most 10 of 107 failing, before or in SCREEN (the replay's rule: failures times 10 below the attempted) |
| Not confirmed | 11 or more of 107; or any protocol failing in screen judging on a schema correction about `quote_date` |

### What else P3 must record that P2b did not

- The index day, read from the SCREEN reports and given to the replay (section 3), so level (b) is printed.
- `cascade.judged_store.read` 0 on every SCREEN report (section 3).
- The third column of target 1 (section 4), by hand until P3-H1 lands.
- The per-report comparison of tcga with P2b (section 6).

## 6. The pathology target: the five reports

**What cannot be named (shown).** PoC-1 kept counts only: "counts only: no raw answer, no patient id"
(`docs/plan/measurements/poc-1-2026-11-15/sets-b266f9b7.json`, `meta.note`). No branch holds PoC-1's answers
(H-18, section 2). So no report can be matched between PoC-1 and P2b, and "the five reports" are a net difference of
two totals, not five reports. Which reports moved, and whether more moved both ways, is not in any record.

**What can be named (shown).** P2b stores an answer per report: `tcga.tgz`, `work/answers.json`,
`Gm3TCGA-BRCA.patients.<pseudonym>.verdicts`, joined to the public TCGA case id by `work/pidmap.json` and
`built/gold/ids.json` (`patients`). So every one of P2b's 379 excluded, 48 listed and 73 open reports is named, and P3
can be compared with P2b report by report.

**The run-to-run variation the records show (shown).**

| Record | Excluded of 450 | Open | Source |
| --- | --- | --- | --- |
| PoC-1, `b266f9b7`, gate open | 384 (85.3 %, 95 % interval 81.7 to 88.5) | 68 | `poc-1-evidence.md`, the tcga rows |
| PoC-1, the same compile, second job | the pair said "fail" on 377 (83.8 %, 80.0 to 87.1) | 75 | the same: "The 7 extra catches are the run-to-run difference of the pair, not the gate" |
| P2b, `57263236` | 379 (84.2 %) | 73 | `replay.json`, `targets.pathology.run`; H-18 section 2 |

- One compile, two jobs, one commit: 7 apart. P2b's 379 lies between PoC-1's two jobs, and inside PoC-1's own 95 %
  interval for 384 (81.7 % to 88.5 % of 450 is about 368 to 398).
- H-18 found no change on the decision path from `b266f9b7` to `57263236` that applies to these reports (the prompt
  file and judge schema unchanged; the rule for an inclusion's "fail" unchanged). This page found none from
  `57263236` to `3f6a02ec` either (target 2's table above).

**Recommendation: the target needs a tolerance; no fix is owed before P3.**

- **Not a fix owed (shown as far as the records go).** No code change on the path explains the 5; the one change
  since P2b (#997) does not change a tcga verdict. The two tcga verifier replies that are no JSON (H-18: TCGA-AZ-5403
  and TCGA-RC-A6M4, cut off twice) are P2b's 2 `failures`, the same count as PoC-1's 2 (`judging.failures`). They
  leave 2 reports open in both runs and are worth a card, but they do not explain a move from 384.
- **Not "the number moved" by a change (hypothesis).** The likeliest cause is the run-to-run difference of the pair,
  which PoC-1 measured at 7. The records cannot prove it, because PoC-1 kept no answers.
- **A tolerance (needs a ruling).** As coded, the target is met only by exactly 384 (`replay.py`). PoC-1's own second
  job (377) would not be within it. A ruling the integrator or the owner could give, for example: "excluded within
  PoC-1's 95 % interval (368 to 398 of 450), with 0 wrong exclusions and 0 of 50 eligible lost", or "not below the
  lower of PoC-1's two jobs (377)". This page does not choose: it is a rule for the target's owner (question 3).

**How P3 records per-report answers so the question cannot recur.**

1. Keep P3's `tcga.tgz` whole (built and work folders) on a hand-over branch, as P2b's is. It already holds every
   report's verdict, quote and basis.
2. Check P3's tcga `built/gold/ids.json` sha256 against P2b's (`711e3756fac788a7...`): the same reports.
3. Compare P3 with P2b report by report: which of P2b's 379 P3 left open or listed, and which P3 excluded that P2b did
   not, each with both runs' replies. Until a tool does it (P3-H4), a short script over the two `answers.json` files
   does, through `pidmap.json` and `ids.json`. The moved reports, both ways, are the run-to-run difference measured
   directly.

## 7. The estimate

US$2.74 a VM hour, spot (`tools/complete_run.py`, `PRICE_PER_HOUR`). The disk and the bucket are not in these
figures.

**The driver's own estimate (run here).**

```
$ deploy/gcp/box-run.sh --estimate --mode validation --steps dev,acc --only jmed:300,tcga:500,sigir
  jmed: JMED-Personas, 300 patients x 2 criteria (ja)                  0-540
  tcga: TCGA-Reports, 500 reports x 10 cancer-type criteria          72-2304
  sigir: SIGIR, physician criterion labels (1,015 criteria,         684-3708
  b01-b03 clone, venv, images (this VM, 2026-11-15)                      198
  02 the stack up by the direct route (this VM, 2026-11-15)              281
  03-07 env, pins, serving record, G-1, canary                           260
  08 trialbox eval qualify --box (full)                              unknown
  known part 0.42 to 2.03 h (US$1.14 to US$5.55 spot); 2 step(s) unmeasured, bounded by the cap: 6 h = US$16.44 spot / US$49.32 on demand
exit 0
```

Its set rows are the plan's call counts at a rate the plan calls superseded (H-12 found the same). P2b's actuals
replace them; the driver's figure that holds is the cap, 6 h.

**P2b's actuals (shown).** The run's own step minutes (`summary.json`, `minutes`): 141.58 minutes in all steps,
2.36 h; the sets `60-acc-jmed` 2.09, `61-acc-tcga` 6.39 and `62-acc-sigir` 112.22 minutes; every other step 20.88
minutes, `07g-gate` 0.09 of them. The run lasted 07:38 to 10:02 UTC, 2.40 h, US$6.6 (H-18; the lead's brief).

| | Low | Estimate | High |
| --- | --- | --- | --- |
| Everything but sigir (P2b: 2.40 h less sigir's 1.87 h) | 0.53 h | 0.53 h | 0.53 h |
| The gate step at its longest (480 s against 5 s measured) | 0 | 0 | 0.13 h |
| sigir, 104 protocols | 1.87 h (P2b: 64.7 s a protocol) | 1.97 h (P2b plus the 3 protocols that now screen and #996's note lines) | 3.00 h (its budget, 10,800 s: P1b's 96.5 s a protocol, no gain from three in flight) |
| **Total** | **2.40 h, US$6.58** | **2.50 h, US$6.85** | **3.66 h, US$10.03** |

- **The estimate to post: US$6.9 (2.5 h).** The stop line, 50 % over it (the owner's rule, plan 42 section 3):
  **US$10.3**, 3.75 h. The high figure lies under the stop line by construction: sigir's budget ends the set first.
- **The worst case: the cap, 6 h, US$16.44.** The VM powers itself off at its cap. Reaching it would take a fault
  past the set's budget: a stalled step, or a pre-emption and a resume (H-12: a resume costs about 0.29 h more).
- **sigir's budget.** P2b gave 7,200 s and used 6,728.1 s, 93 % (`work/set-clock.json`). 10,800 s holds the high
  rate for all 104 protocols (104 x 96.5 s = 10,036 s, plus the 600 s a protocol needs to start). A protocol the
  budget still cuts is now taken up by one resume with a budget for it (D-1129, on master since train 70), not by
  redoing the set.

**The money.** The running total and P2b's figures are the integrator's (the lead's brief: "about US$132 of 200"),
not read again here.

| | Running total | Left of US$200 |
| --- | --- | --- |
| Before P3 | about US$132 | about US$68 |
| After P3 at the estimate (US$6.9) | about US$138.9 | about US$61.1 |
| After P3 at the stop line (US$10.3) | about US$142.3 | about US$57.7 |
| After P3 at the cap (US$16.44) | about US$148.4 | about US$51.6 |

## 8. The launch sheet

In the form of H-7's sheet (`launch-sheet-2026-11-17.md`). The owner's yes comes first. Every step but the last is
free.

### The ids, under the tag (run here)

```
$ PYTHONPATH=libs:services:. .venv/bin/python -m tools.box_run acc-ids --only jmed,tcga,sigir --rs-tag m4
 jmed  "prefix": "Mm4", "ids": ["Mm4JMED-DM", "Mm4JMED-HT"]
 tcga  "prefix": "Gm4", "ids": ["Gm4TCGA-BRCA", "Gm4TCGA-COAD", ... "Gm4TCGA-UCEC"]
 sigir "prefix": "Sm4", "ids": null, "how": "not known here: the sample is drawn from the set's source files, not in the local cache"
 "refused": []
exit 0
```

Pass no `--acc-protocols` for sigir (H-7, section 2).

### The source bundle (run here)

In a full clone (this container's was shallow; `git fetch --unshallow origin master` first), at the launch commit:

```
$ PYTHONPATH=libs:services:. .venv/bin/python -m tools.box_run src-bundle --commit 3f6a02ecc703582667ad2027233043f870ca8790 --out <bundle>
 "commit": "3f6a02ecc703582667ad2027233043f870ca8790", "ok": true, "head": "3f6a02ecc703582667ad2027233043f870ca8790"
exit 0
```

If master moves before the launch, make the bundle again at the new commit and run every check below again.

### The command line

```
deploy/gcp/box-run.sh --mode validation --steps dev,acc \
  --release-id dev-<commit12> --commit <full sha> --src-bundle <bundle> \
  --only jmed:300,tcga:500,sigir --acc-rs-tag m4 \
  --acc-protocols "tcga:Gm4TCGA-BRCA" --acc-streams "sigir:3" \
  --acc-deadline "jmed:3600 tcga:2400 sigir:10800" --acc-min-start 600 \
  --skip 08-qualify --no-wait
```

- The sets run in the order given; jmed, the first, is the gate set (H-7, section 4).
- `--skip 08-qualify`: left out and said, never a pass; the qualification is its own run (H-15).
- The VM's `deploy/.env` must not carry `TB_SCREEN_MAX_PAIRS` (H-7, section 4).

### The free checks, in this order

1. **The ids** (above). Must list `Gm4TCGA-BRCA`; `"refused": []`.
2. **The estimate** (section 7). Post it on #639 with the worst case, the stop line and the running total before the
   start (D-505).
3. **The preflight.** The line above with `--preflight` after `box-run.sh`. Run here at `3f6a02ec` with the proved
   bundle, exactly the line above, it printed:

   ```
   validation-check: a VALIDATION box can route the run's calls
   preflight: ok     the steps are known
   preflight: ok     the launch's options would hold on the VM (filter, tag, streams, budgets, commit)
   preflight: ok     protocols in flight per set (D7: 3 for a compile-bound set unless --acc-streams): {'jmed': 1, 'tcga': 1, 'sigir': 3}
   preflight: ok     the source bundle is proved (D8): cloned as the VM clones it, the commit checked out
   preflight: ok     the metadata builds (every key the steps need, no key-like value)
   preflight: every free check passed (nothing was uploaded or started; ...)
   exit 0
   ```

   Every line must read `ok` and the exit code must be 0. Exit 2 is the filter, 6 the preflight, 9 a blocker of the
   validation-check.
4. **The wrong id, once.** With `--acc-protocols "tcga:Gm3TCGA-BRCA"` (P2b's tag) it stopped with exit 2: "tcga:
   Gm3TCGA-BRCA not among its ids (prefix 'Gm4'; ...)" and "refused (no VM started)". Run here.
5. **The day.** The launch day in the box's zone is not 2026-11-17 (section 3).
6. **The rulings of section 9**, or the integrator's word that P3 runs without them.

The paid launch is the same line without `--preflight`.

### After the run (free)

1. `deploy/gcp/box-run.sh --collect <run id>`: each set's `acc/<set>/score.json` and the run's `acc-score.json`.
2. The day: every SCREEN report's `run_date` (`work/screen/*.json`); one day, `<D>`.
3. `python -m tools.public_accuracy.replay <the run folder> --index-day <D> --build-day <D> --json replay.json`:
   levels (a) and (b). Target 3's level (b) is not to be read until H-18's card on `rerun.judge_replies` lands.
4. `python -m tools.public_accuracy.trace sigir.tgz tcga.tgz jmed.tgz --ref <D> --json trace.json`: each wrongly
   excluded pair by line and stage; the third column of target 1 by hand from it (section 4).
5. `cascade.judged_store.read` is 0 on every SCREEN report (section 3).
6. tcga against P2b, report by report (section 6).
7. Print each figure three ways (section 4), with "within the target" and never "met".

### If it stops

As H-7, section 8, with one change: a set its own budget cut is taken up by `--resume <run id> --acc-deadline
"<set>:<s>"`, which runs only what was cut (D-1129). `box-run.sh --preflight --resume <run id>` says first what the
resume would do.

## 9. What is not ready

| Item | Blocks the launch? | Why | Owner |
| --- | --- | --- | --- |
| The owner's yes | **yes** | the rule | the owner |
| The free checks at the launch commit | **yes**, until run again | master moves; run here at `3f6a02ec` only | the integrator |
| The owner's ruling on setting the age-line class aside | **decides target 1's reading** | without it, P3's best expected figure without the six is 3 of 420 | the owner |
| The ruling on sigir-20154 x NCT01701453, INC-06 (lane A2 proposes "conflicted") | **decides target 1's reading** | without it, P3's best expected figure without the six and the class is 1 of 418 | the integrator |
| A tolerance for target 2 | **decides target 2's reading** | as coded, only exactly 384 is within; PoC-1's own second job (377) is not | the integrator or the owner |
| jmed asks no note question (S3 judged 0) | no | jmed's 0 of 330 is printed as "not evidence" until it lands | lane A2 (H-18's card) |
| The third column printed by a tool (P3-H1) | no | by hand from `trace.json` | lane H |
| The day in the stored set and read by the replay (P3-H2) | no | given by hand from `run_date` | lane H |
| The replay keeps a stored coded fail on a re-compiled note line (P3-H3) | no | level (b) cannot show #996 until it lands | lane H |
| `rerun.judge_replies` through the box's path | no | target 3's level (b) not to be read | lane H (H-18's card) |
| `SM3NCT01863628-EXC-06` still excludes every woman at S1 (P3-A1) | no | its only gold pair is "would consider" | lane A2 |

**Today, technically, P3 could be launched**: the free checks pass at `3f6a02ec`. Whether it is worth its cost
depends on the three rulings: without them, the expected target-1 figure is not within the target under any of the
three readings, and target 2's is within only by chance. P3 would still confirm #996 and #997 on the box, and measure
the pathology variation report by report against P2b.

## 10. Proposed cards

One line each; they go through the integrator. Sizes: S is a day or less, M a few days.

- **P3-H1, lane H, M** (the replay and the scorer): print target 1 three ways, the age-line class by a rule the card
  fixes in a decision (a pair labelled eligible, excluded on a line whose only logic is an age, where the age the key
  itself gives the patient fails that line), each marked pair by id, never relabelled. Evidence: section 4; H-18,
  section 1.
- **P3-H2, lane H, S** (the driver and the replay; the driver files were last changed for this by lane H's H-14):
  `box_vm.py acc-set` keeps the build day and the snapshot in `work/set-clock.json` (`step_acc_set` passes
  `acc_today`); the replay reads them, else one `run_date` of the SCREEN reports, before it gives up on level (b).
  Evidence: section 3; H-18, section 4.
- **P3-H3, lane H, S** (`tools/public_accuracy/rerun.py`, `rescreen`): a stored coded verdict on a line the re-compile
  no longer codes is open ("needs the notes; not re-run"), not kept. Evidence: section 5, the re-compile of
  `SM3NCT01227499-EXC-04` and level (b) at 4 of 420.
- **P3-H4, lane H, S** (`tools/public_accuracy/trace.py`): two stored tcga sets compared report by report by the
  public case id, the moves both ways with each run's replies. Evidence: section 6.
- **P3-A1, lane A2, S** (`services/criteria_compiler/ir_extract/postprocess.py`): an exclusion compiled to a sex alone
  whose text names a condition ("in pregnancy and lactation;") with no concept candidate is not caught by #996.
  Evidence: section 5, `SM3NCT01863628-EXC-06` re-compiled from P2b's stored reply.
- **P3-A2, lane A2, S**: the two tcga verifier replies that run on until cut off (TCGA-AZ-5403, TCGA-RC-A6M4 in P2b,
  2 `failures` as in PoC-1): why the reply runs on, and whether the answer's token budget is the cause. Evidence:
  H-18, section 2; `tcga.tgz`, `work/raw-traces.json`.

Still open from H-18: lane A2's JMED condition lines; lane H's `rerun.judge_replies`; lane H's question on whether the
key's builder should still write a line for a pair the physicians labelled eligible.

## 11. Questions

1. **The integrator:** does P3 wait for the three rulings of section 9, or run now and read them afterwards?
2. **The integrator:** INC-06 x sigir-20154: "conflicted" (lane A2) or left as a wrong exclusion?
3. **The integrator or the owner:** target 2's tolerance. As coded only exactly 384 is within. PoC-1's 95 % interval
   (about 368 to 398 of 450), the lower of its two jobs (377), or another?
4. **The owner:** the age-line class (sigir-201422's two pairs): set aside from the target's reading, or not?
5. **The integrator:** does trec2023 stay out of P3 (section 2), and does it keep tag `m4` (no collision with P3's
   sets)?
6. **The integrator:** is the running total about US$132, and is P2b's US$6.6 in it?

## Not shown

- **The `fix:` corrections to H-7's sheet.** No line starting `fix:` is in `launch-sheet-2026-11-17.md` on master or
  on branch `claude/lane-h-7-launch-sheet`. If they are on #639, this page has not read them (it reads no GitHub).
- **What P3's models will answer.** Every P3 figure in section 5 is a hypothesis: P3 extracts and judges afresh.
- **Whether the judged-pair store survives between launches on this VM** (section 3).
- **The 5 pathology reports by name** (section 6).
- **trec2023's figures** in section 2 are derived from two runs on different commits, not measured.
- **H-26's page** (`p2b-compile-and-coverage-2026-11-17.md`, written by another lane H session) was not on master
  when this page was written and is not read here.
