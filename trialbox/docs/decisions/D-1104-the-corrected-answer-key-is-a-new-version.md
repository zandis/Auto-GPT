# D-1104 the corrected answer key is a new version; the old one stays

- **Task:** lane H, card H-2 (the benchmark builder's fixes B1 to B3 after launch P1b; the integrator's list on #649,
  2026-11-16T11:52:42Z); the owner's requirement: the corrected key is a new versioned file, the old one stays
- **PR:** this branch (`claude/lane-h-2-benchmark-key`)
- **Date:** 2026-11-17
- **Status:** proposed
- **Builds on:** lane G's PR #889 (B1 to B3 in the builder, S1 to S4 in the scorer)

## Context

The answer key of a public accuracy set is what `tools/public_accuracy` builds at run time from the pinned sources:
the gold labels in `built/gold` (`pairs.jsonl`, `criteria.jsonl`, `ids.json`, `compile_gold.json`, `bundle.json`)
and the placed facts in `built/site` they are scored against (each patient's birth date, the age and sex lines
written into a protocol). It is never committed; a launch stores its own `built/gold`.

Three reviews of launch P1b (run `box-20261116T074927Z-3b2f5e38`) found faults in that key: B1 a birth date of 1 July
(24 of 46 sigir patients a year too old on the run day, an infant 0 years old), B2 placed age lines in years
("Aged 0.17 years or older" for "2 Months") and written again when the protocol states the bound, B3 the JMED truth
read from the structured 主病名 / 既往歴 / 現病歴 while the box reads the persona note. #889 corrected the builder in
place: after it, P1b's key could no longer be built, and nothing said which key a score was scored on.

## Decision

1. **Two versions, by name** (`tools/public_accuracy/key.py`): `v1` is the key as launch P1b used it (the builder of
   master `fa639b61`), `v2` has B1 to B3. A new version is a new entry; an entry is never changed. `v2` is the
   default; `python -m tools.public_accuracy build --key v1` still builds v1. Every reader (`sets.read`,
   `read_trec`, `read_sigir`, `read_jmed`, `placed_lines`) and `site.build` take the version; an unknown one is
   refused.
2. **The old key stays byte for byte.** `--key v1` writes every file the `fa639b61` builder wrote with the same bytes
   (pinned by sha256 in the test, computed with that commit's code). Two new files sit beside them: `gold/key.json`
   (the version) and `gold/written.json` (#889's list of the lines the benchmark wrote, for S3 and S4). A folder
   without `key.json` (P1b's stored folders) is v1. `eval/public_accuracy_key/MANIFEST.json` pins the sha256 of each
   file of P1b's stored `built/gold` for sigir and jmed.
3. **A score names its key.** `python -m tools.public_accuracy score` writes `answer_key` (version, what it is,
   whether the folder says so itself) into `score.json`. The field is not named `key`: `score.score(built, work,
   key=)` already takes `key`, the site's pseudonym key. `score.score` and `box_run acc-score` belong to cards H-3
   and H-1; they add the same field with `tools.public_accuracy.key.describe(built)` (imported under another name).
4. **`key-diff` lists what differs, and why**: `python -m tools.public_accuracy key-diff OLD NEW` (`key.diff`) gives
   one row per (set, patient, protocol, criterion or line) whose label, birth date or protocol line differs, with
   the fix that changes it (B1, B2, B3), and names what it could not compare (a stored folder holds `built/gold`
   only).
5. **v2 judges the same JMED patients as v1.** #889 also drew the JMED sample by the note's strata, so v2 would have
   been a different sample and P1b's answers could not be scored on it. The sample is drawn by the structured fields
   in every version (a sampling frame, not a truth); only the label and its stratum come from the note.
6. **A risk, a tendency, a borderline or pre- state is not the condition** (v2's truth, `sets.jmed_stratum`). On
   P1b's notes #889's rule read "糖尿病のリスクは低い", "境界型糖尿病", "高血圧リスク", "高血圧傾向" and "糖尿病予備群"
   as the patient having it. A mention followed by リスク / 傾向 / 予備群, or after 境界型 / 境界域, is not "own".
7. **The physicians' labels are not relabelled.** B1 and B2 change the site, not a SIGIR or TREC label. The 2 sigir
   pairs whose pair label conflicts with the physicians' own criterion labels stay as the physicians gave them; the
   scorer reports them apart (S1, card H-3).

## What changes between v1 and v2 on launch P1b's key

- **jmed, labels (B3):** read from each note the run's judge read in full (319 of the 594 rows the box answered), 11
  labels change. Of the 7 wrong exclusions on the exclusion line, exactly 3 were key faults, all on JMED-HT, now
  `excluded`: `f1f374875280433d8fdec6ff9ced4c28`, `9f56d1cf27804387be624da5005a7f03`,
  `f5da14174f2f4fba864c0e161bb49c21` (the note says 併存疾患として高血圧 / 軽度の高血圧があり). The other 4
  (`780cf644…` DM, `ec71ddce…` HT, `9f56d1cf…` DM, `928744f7…` HT) stay wrong exclusions: the note names a medicine or
  a risk, not the condition. Eight labels go from `excluded` to `not excluded` (the note does not say it, or says a
  pre-state): `5c640947…` HT (the box excluded it), `a5816632…`, `ec1cfd65…`, `13b716f8…` HT, `7a001f60…`,
  `a4b4ea57…`, `f18b4d8e…`, `7a329699…` DM. The full ids are in the manifest. The other 275 rows' notes are not in the
  stored run: their v2 labels need the source (a v1 and a v2 build and `key-diff`).
- **jmed, birth dates (B1):** every patient's (the visit minus the age, not 1 July).
- **sigir, labels:** none. The 2 conflicts are `sigir-201413` x `NCT00163709` (a 30-year-old; the box excluded on
  "Aged 40 years or older", as the physicians' criterion label does) and `sigir-20142` x `NCT00711399` (the box
  excluded on "Respiratory distress", which the physicians label `excluded`): S1's to report.
- **sigir, birth dates (B1):** 43 of 46 change (the other 3 have no note in `eval/criterion_ml` to check here); under
  v1, 24 of the 43 were a year too old on the run day. `sigir-201418` (6 months old) was born 2026-07-01 under v1
  and 2026-02-28 under v2: with B2's "Aged 2 months or older" for `NCT01260883` the box's exclusion of this eligible
  pair on "Aged 0.17 years or older" no longer follows from the key.
- **sigir, protocol lines (B2):** the placed age lines of each protocol; the full list needs ClinicalTrials.gov's
  fields, which are fetched at build time.

## Test

`tests/unit/test_h2_answer_key_versions.py`: v1 is built byte for byte as `fa639b61`'s builder (34 files pinned);
a folder without a version is v1 and an unknown version is refused everywhere; each version's lines and birth
dates; `key-diff` between a v1 and a v2 build lists exactly the B1, B2 and B3 rows and the same JMED patients;
`key-diff` on a stored gold folder names what it could not compare; P1b's jmed slice
(`tests/fixtures/public_accuracy_p1b`) gives exactly the 3 key faults among the 7 wrong exclusions; the manifest
keeps v1's P1b sha256; a score names its key.
