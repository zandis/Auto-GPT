# D-1111 the offline replay of a stored launch scores it again and re-runs what needs no model, each figure labelled

- **Task:** lane H, card H-4 (the offline replay of launch P1b; plan 42 section 3, the three targets of the
  confirming launch)
- **PR:** this branch (`claude/lane-h-4-replay`)
- **Date:** 2026-11-17
- **Status:** reserved
- **Builds on:** D-1104 (the answer key's versions), D-1107 and D-1108 (the scorer's protocol block and "not scored")

## Context

Launch P1b (run `box-20261116T074927Z-3b2f5e38`, commit `3b2f5e38`) stored, per set, its built gold and its work:
each protocol's FEAS state, error, draft criteria and per-patient verdicts (`answers.json`), and the model calls it
made (`raw-traces.json`). Lane A2's fixes (F1 to F6, G1 to G12) and lane H's key and scorer fixes landed after it.
Whether they move the three targets could only be learnt by a paid launch. Most of the answer needs no model: the
compile from the stored model replies, the causes the review named for each failure, the coded age lines, and the
checks that run after a model's verdict.

## Decision

1. `python -m tools.public_accuracy.replay RUN ...` reads stored sets (the driver's tarballs, extracted folders, or
   folders of them) and prints a table and, with `--json`, a report (`schema_version` 1) naming the commit, the key
   versions, each set's figures and the three targets. It calls no model, no network and no GPU, and changes none of
   the code it calls.
2. Every figure carries its level:
   - **(a) re-score.** The stored verdicts scored by the current scorer through the driver's own path
     (`tools.box_run.acc_score`), on key v1 (the run's own gold) and key v2. Key v2 offline is v1's gold with the
     label rows `eval/public_accuracy_key/MANIFEST.json` lists for that run, applied where each matches one row; what
     the list does not cover stays v1 and the report says so.
   - **(b) re-run of the deterministic parts** (`tools/public_accuracy/rerun.py`). `Compiler.compile` runs on the
     protocol lines the run sent to `ir_extract`, with a model that answers only from the stored replies. A line the
     run asked about with no stored reply makes the protocol "not re-run". The CQL translator, the FHIR server and the
     box's lake are not run, so a FEAS or APPROVE failure is checked by the cause the review named (G1 a ValueSet id
     over 64, G2 an encounter with no code, G5 `None` in the CQL) on the ruleset the current compile writes. SCREEN's
     deterministic steps run on it (G6, G7), and the stored judge replies are read again (G8). Coded lines whose whole
     logic is age and sex are decided again from their own SQL, on an in-process lake, at the patient's age on the
     run's day under each key's birth date (from the public note where the repository holds it; else from the ages the
     patient's stored coded verdicts allow). Stored note exclusions get the current inference guard (F6). A note
     verdict, a missing reply and a time budget stay as stored.
3. A stored tarball is untrusted. It is unpacked into a new empty folder outside the repository, member by member;
   an absolute name, a `..` part, a link or a special file refuses the whole archive before anything is written.
   Nothing in it is run.
4. The exit code is 0 when the replay ran, whatever the figures. `--require-targets` exits 3 when a target is not
   met at the highest level the replay reached.

## Test

`tests/unit/test_h4_replay_2026_11_17.py`, on a small run cut from P1b's stored sets (public SIGIR 2016 and
synthetic JMED-Personas; chart numbers made at run time from offsets): the safe extractor's refusals; the P1b
record on key v1; key v2 applied; a FEAS failure whose ValueSet id cause is gone; an `ir_extract` failure not re-run;
a coded age exclusion decided again on both keys; tcga "not scored".
