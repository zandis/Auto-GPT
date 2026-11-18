# The ladder report on launch P2b's stored sets, 2026-11-18 (card 10A-3)

**Reader:** lane H's lead, and the lanes whose rungs the report counts

Plan 10's row 10A-3 (sources 9c-1, B16-16, 17-2): the ladder report, widened, with decisions per rung by criterion
kind, note language and site, and the decided share beside every accuracy figure and every bound. This page shows
the report on the stored P2b sets: run `box-20261117T073759Z-57263236`, branch `integrator/p2b-artefacts` at
`2bcf5ca9` (`sigir.tgz`, `jmed.tgz`, `tcga.tgz`; never merged). The data is public: SIGIR 2016 (NCBI TrialGPT),
JMED-Personas (CC BY 4.0) and TCGA-Reports (CC BY 4.0). No model, GPU or network was used.

## What changed

- `tools/public_accuracy/ladder.py`: the report. A cell is one verdict of one patient on one criterion; its rung is
  read from the verdict's basis through a table kept as data (`RUNGS`: rules, terminology, rule extractor, meaning
  search, judge with verifier, person, unknown; a basis the table does not know prints as its own rung); it is
  decided when the verdict is pass or fail. Every share carries the scorer's exact 95 % interval.
- `tools/public_accuracy/criterion_kinds.json`: the criterion kinds as data (19 kinds of review 15 section 3, with
  English, Japanese and Traditional Chinese patterns).
- The scorer (`score.py`, layout 5) puts `ladder` in every set's score, and the run's summary carries it
  (`tools/box_run.py`). The replay (`replay.py`, layout 3) prints the decided share beside each target figure and
  adds a fourth section, the ladder, per level.

## The commands

```
python -m tools.public_accuracy.ladder sigir.tgz jmed.tgz tcga.tgz
python -m tools.public_accuracy.replay sigir.tgz jmed.tgz tcga.tgz --no-rerun
```

## The rung table, as printed

```
Which rung decided each patient-criterion cell (decided: pass or fail; the rest is open)
                         cells     rules     judge    person   unknown  decided
jmed                      1118       592         0         0       526  decided 592 of 1118 (53.0 %, 95 % CI 50.0 to 55.9 %)
sigir                      895       103        35       385       372  decided 138 of 895 (15.4 %, 95 % CI 13.1 to 17.9 %)
tcga                       500         0       427         0        73  decided 427 of 500 (85.4 %, 95 % CI 82.0 to 88.4 %)
By note language, all sets:
  en                      1395       103       462       385       445  decided 565 of 1395 (40.5 %, 95 % CI 37.9 to 43.1 %)
  ja                      1118       592         0         0       526  decided 592 of 1118 (53.0 %, 95 % CI 50.0 to 55.9 %)
By site, all sets:
  jmed                    1118       592         0         0       526  decided 592 of 1118 (53.0 %, 95 % CI 50.0 to 55.9 %)
  sigir                    895       103        35       385       372  decided 138 of 895 (15.4 %, 95 % CI 13.1 to 17.9 %)
  tcga                     500         0       427         0        73  decided 427 of 500 (85.4 %, 95 % CI 82.0 to 88.4 %)
```

Review 15, section 2.2: SIGIR 895 cells, coded 103, two models 35, unknown 372, person 385, machine-decided 138
(15.4 %); JMED 1,118, 592, 0, 526, 0, 592 (53.0 %); TCGA 500, 0, 427, 73, 0, 427 (85.4 %). **Equal, every cell.**
Review 17 section 3: "SIGIR cells decided 138 of 895, 15.4 % (Wilson 13.2 to 17.9 %)". The report prints 138 of 895
(15.4 %); its interval is the scorer's exact one, 13.1 to 17.9 %. The tiers equal review 15's too (SIGIR review 83,
excluded 19; JMED 524 and 70; TCGA high 48, review 73, excluded 379).

## Beside the figures, as the replay prints them

```
   (a)   v2            4   420  5/424           no             jmed 0/330, sigir 4/40, tcga 0/50; decided: jmed 592 of 1118 (53.0 %, 95 % CI 50.0 to 55.9 %), sigir 138 of 895 (15.4 %, 95 % CI 13.1 to 17.9 %), tcga 427 of 500 (85.4 %, 95 % CI 82.0 to 88.4 %)
       beside it: tcga decided 427 of 500 (85.4 %, 95 % CI 82.0 to 88.4 %)
3. Protocols failing (target: fewer than one in ten of those attempted fail before or in SCREEN; the share before SCREEN alone is beside it; met only by a launch)
       beside it:; decided: jmed 592 of 1118 (53.0 %, 95 % CI 50.0 to 55.9 %), sigir 138 of 895 (15.4 %, 95 % CI 13.1 to 17.9 %), tcga 427 of 500 (85.4 %, 95 % CI 82.0 to 88.4 %)
```

## The kind table on SIGIR, against review 15's

Review 15 classified the 1,165 SIGIR criteria with 19 regular expressions that were not committed (its section 13,
[M 3]: scripts in a temporary folder). This report's patterns are written to the same 19 kinds; they cannot be
the same expressions, so the kind table is close to review 15's and not equal to it.

| Kind | Review 15: share; decided of cells | This report: share; decided of cells |
| --- | --- | --- |
| age or sex | 16.1 %; 100 of 154 | 16.3 %; 100 of 156 |
| diagnosis | 22.9 %; 20 of 200 | 24.2 %; 18 of 223 |
| medication | 16.7 %; 4 of 143 | 15.6 %; 4 of 128 |
| temporal wording | 28.1 %; 82 of 253 | 28.1 %; 89 of 254 |
| "no history of" or "history of" | 7.9 %; 4 of 71 | 7.1 %; 4 of 64 |
| consent and capacity | 7.7 %; 1 of 64 | 7.0 %; 1 of 60 |
| procedure or device | 7.6 %; 3 of 73 | 7.1 %; 3 of 69 |
| laboratory value | 6.0 %; 0 of 46 | 5.9 %; 0 of 47 |
| pregnancy and contraception | 5.4 %; 6 of 50 | 5.4 %; 6 of 49 |
| counts and repetition | 5.3 %; 2 of 43 | 5.5 %; 3 of 52 |
| vital sign or measure | 4.7 %; not given | 3.6 %; 1 of 33 |
| lifestyle | 4.0 %; 1 of 28 | 3.8 %; 1 of 27 |
| scale or stage | 3.4 %; 2 of 35 | 3.3 %; 2 of 33 |
| allergy | 2.9 %; 1 of 22 | 3.0 %; 1 of 22 |
| imaging | 2.7 %; 1 of 26 | 2.8 %; 4 of 27 |
| another study | 1.7 %; 1 of 16 | 2.1 %; 1 of 19 |
| investigator judgement | 1.5 %; 1 of 11 | 1.6 %; 1 of 15 |
| study logistics | 1.1 %; 1 of 11 | 1.4 %; 0 of 9 |
| biomarker | 0.4 %; 0 of 3 | 0.3 %; 1 of 4 |
| matched no kind | 18.0 %; not given | 17.9 %; 10 of 159 |
| two or more kinds | 638 of 1,165 (54.8 %) | 501 of 1,165 (43.0 %) |

Equal: the temporal and pregnancy shares, and the machine-decided cells of 12 kinds (age or sex 100, medication 4,
history 4, consent 1, procedure 3, laboratory 0, pregnancy 6, scale 2, lifestyle 1, allergy 1, another study 1,
investigator judgement 1). Different by a few criteria: the rest, and the multi-kind count (this report's
expressions overlap less). The reading of review 15 holds on either table: age and sex lines and temporal wording
are the decided kinds; diagnosis, medication, laboratory, consent and history are almost never decided on SIGIR.

## Not shown

- The kind table equal to review 15's, cell for cell: its expressions are not in the repository. The rung table,
  which is the measured one, is equal.
- Level (b) of the replay: the run's record names no index day (as in the P2b review).
- A site with more than one protocol site: each public set is one site; `ids.json` may name a site per protocol and
  the report then splits by it (a unit test shows it on synthetic data).
- The nightly (plan 9's V22): not wired here.
