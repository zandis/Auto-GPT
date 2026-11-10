# TrialBox validation and evidence

*Owner: Product owner. Status: living; changed in the same pull request as the code it describes. History: the git log of this file; the merge into eight documents is D-139.*

For the owner and the reviewers. It lists every gate, what it checks, how to run it, and the last measured result.
The numbers come from the head of `master` unless a date says otherwise; each names the decision that recorded it.

## 1. The gates

Run in `trialbox/` with the venv (`make venv`). All use synthetic or public data, the stub model, no network.

| Gate | Command | Checks | Last result |
| --- | --- | --- | --- |
| lint | `make lint PY=.venv/bin/python` | contracts fresh, ruff, ruff format, mypy --strict, doclint | clean |
| suites | `pytest -q -m "not integration and not e2e and not llm and not perf" tests/unit tests/console tests/testbench` | unit, console pages, testbench | 1,405 passed, 2 skipped (D-139) |
| **the build gate** | `make e2e-simple` (`tools/e2e_simple.py`) | the whole path on a 5,000-patient synthetic hospital, every count recounted from the source | PASSED in 115 s (D-139) |
| public data | `python -m tools.public_e2e --lang ja` | the same path in the console on real public notes | 112/112 (D-139) |
| the walk | `node tools/public_walk.js` against `public_e2e --serve` | 5 roles × 3 languages × desktop and phone: status, language, no English on ja/zh-TW pages, axe-core, 44 px targets, tap counts | 780 checks over 768 pages, 0 failures; axe 0 serious or critical (D-139) |
| backup | `make backup-drill` (`tools/backup_drill.py`) | backed up, wiped, restored: every table, file, mark, participant, site set-up and code list the same | PASSED, 11 checks in 112 s (D-139) |
| update | `python -m tools.update_drill` | a signed update applied; a tampered bundle refused; a bad migration and an unhealthy release rolled back | PASSED, 12 checks in 247 s (D-139) |
| OMOP parity | `python -m tools.omop_parity --json eval/omop_parity/report.json` | the lake exported from OMOP equals the flattened lake row for row; FEAS and every patient's verdicts equal for all 7 committed rulesets on the synthetic hospital, the public site and the MIMIC demo; DQD-style checks on the store | identical on all 4 data sets (0 patients different); DQD 0 failures but 1 on MIMIC (visit classes without a concept) (D-151) |
| documents | `python tools/doclint.py` | the eight documents, links, headings, paths, no retired name | clean (D-139) |
| complete run | `python -m tools.complete_run` | every part above in ja and zh-TW and the scenario matrix, with a screenshot per stage | PASSED, 662/662 checks, 84/84 screenshots in 34 min, stub, 5,000 patients, 12 known findings reported (`eval/complete_run/2026-11-09-matrix-stub-5000/report.md`, D-141) |

`tests/integration` (with `TB_INTEGRATION=1` and the compose test stack) adds HAPI CQL, the equivalence gate, the HL7
validator and mail. `make test-e2e` runs every mail scenario against the stack. `tests/llm` needs a real model.

**The committed goldens** (`tests/golden/`, `make goldens-check`, T-006, D-205) are the merge gate for every
data-core branch: the FEAS funnel and the SCREEN candidate set (after the coded filters) of every committed ruleset,
the FEAS basis table, a per-column hash of every lake table and the lake schema, computed from fixed inputs (the
synthetic hospital of profile `ci` with planted site inputs, its next night with a tenth of the records deleted, an
SS-MIX2 storage and the SIGIR public notes; Asia/Tokyo and Asia/Taipei; a fixed synthetic site key) and compared with the committed JSON;
any difference fails with the changed values by path and a unified diff. The same goldens hold for both lake sources
(`TB_LAKE_SOURCE=omop make goldens-check`), so they also pin the OMOP parity, tombstones included. A deliberate
change regenerates them in the same pull request (`make goldens REASON="D-nnn: ..."`); the 50k funnels are written
only from the report of a paid run (`--from-report`). Last result: identical from either source, 17 goldens, about
100 s (D-205). `tests/unit/test_goldens.py` keeps the schema golden and the one-golden-per-ruleset rule in every
`make test`.

## 2. What `e2e_simple` proves

One synthetic hospital (two sites of 2,500 patients, notes 90 % ja or zh-TW and 10 % en), checked against things it
did not compute itself: the generator's counts, a recount from the hospital CSVs, the sent mail, the audit chain and a
byte-identical re-run.

| Stage | What |
| --- | --- |
| 0 | lake counts equal generator counts; no chart number, ID or phone column; keys are pseudonyms |
| 1–2 | criteria pasted, FEAS report with provenance and no model; the investigator approves; a coordinator cannot |
| 3 | SCREEN: funnel never grows; no note excludes without two models (stub: never) |
| 4–5 | marks and their history; N1 and N2 mail with no chart number or name; ready and needs-information lists |
| 7, audit | REDCap read-back, screening log XLSX; reveals audited; the chain verifies |
| 8–9 | REDCap write-back; the data core with REDCap off and on, conflicts, a PI's sheet |
| 10 | built-in forms, entry, history, ODM and REDCap CSV round trip |
| 11 | lifecycle: enrolled, visit due, overdue, done, AE, withdrawn; three counts agree |
| 12 | a new site from a protocol, charts, an IT dump and a messy list; readiness green |
| 13 | Japan: SS-MIX2 equals its CSV export; JP Core `$validate`; licensed lists |
| re-run | FEAS and SCREEN byte-identical (FR-REP-02) |

The budget is 15 minutes; it runs in about 2. `.github/workflows/trialbox-e2e.yml` runs it on every pull request.

## 3. The model gate

The pair (judge Gemma 4 26B-A4B NVFP4, verifier Qwen3.5-9B AWQ) excludes on a note only when both say "fail".

| Measure | Gate | Deployed files on the card | Where |
| --- | --- | --- | --- |
| N-11: eligible SIGIR pairs lost, of 79 (EN / JA / zh-TW) | ≤ 5 / ≤ 4 / ≤ 2 | 4 / 3 / **not recorded** | `eval/parity/replay.json` |
| N-12: TREC CT eligible pairs wrongly dropped, audit-adjusted | ≤ 5 % | **3.1 %** (95 % 1.8–5.0), pass | `eval/trec_ct/results/n12_deployed_2026-11-08.md` |
| pair canary (54 cases, en/ja/zh-TW) on the PRO 6000 | 0 wrong exclusions | judge 54/54, verifier 49/54, 0 wrong exclusions | `eval/parity/gpu-run-2026-11-08-pro6000/` |
| `public_e2e --lang en` with the pair, PRO 6000 | all checks | 98/98 in 1,303 s; 7 disagreements and 1 failure went to review | same folder |

`python -m tools.parity_replay` replays the recorded answers with no model (`--check` checks the committed tables)
and names any recording a GPU run must still add. N-11 zh-TW on the deployed files needs
`eval/trialgpt_compare/results/raw/trialbox__local__gemma-4-26b-a4b-nvfp4__zh-TW.jsonl.gz` and the verifier's file:
`python -m tools.trialgpt_compare run --pipelines trialbox --langs zh-TW --base-url http://<vm>/judge/v1`, then the same
for the verifier (2,030 checks, about 10 minutes on the PRO 6000).
The N-12 audit adjustment rests on a sampled check of NIST labels by Claude, not a clinician
(`eval/trec_ct/AUDIT.md`).

**The serving record** (`tools/serving_config.py`, schema `tb-serving-config/1`): card name, memory, driver, CUDA and
`capped_to`; per vLLM server the image, version, model, served name, quantisation, context, sequences, eager flag,
memory fraction, KV dtype, other flags and the sha256 of every model file. The API key is never recorded.
`python -m tools.serving_config validate <file>` lists gaps; `measured <gpu> <file>` says whether it measures a profile
on its own card (card name, not capped, both models, swap or resident as the profile, context at least the
profile's). The PRO 6000 record is `deploy/measured/serving_config.rtxpro6000.json`.

## 4. Speed and scale

**Hospital scale** (`python -m tools.hospital_sim scale`, stub model, the cascade S0–S5 with the DL-1 pack and recall
certificate; `eval/hospital_sim/results/scale.json`):

| Patients | Generate | Pipeline | Model calls | All checks |
| --- | --- | --- | --- | --- |
| 2,000 | 0.6 s | 40 s | 78 | pass |
| 10,000 | 3.8 s | 173 s | 277 | pass |
| 25,000 | 9.2 s | 468 s | 770 | pass |
| 50,000 | 22.5 s | 805 s | 1,362 | pass |

The projection for 50,000 patients and 12 trials a year (`hospital_sim project`): 18,480 model calls and about 1.2 GPU
hours a year; 9,792 patients for review. It is a model, not a measurement.

**Bench** (`tools/bench.py`, SPEC v1 §11.3, a 4-vCPU, 16 GB host with no GPU; deterministic share only):

| Job | Target | Measured | Projected |
| --- | --- | --- | --- |
| Ingest | 50k patients ≤ 2 h | 15,000 patients in 299 s | 16.6 min |
| FEAS | 300k × 36 month-ends ≤ 30 min | 100,200 patients in 215 s (6 GB cap, spilling) | 11.7 min |
| SCREEN (CQL share) | ≤ 3 h | 600 patients × 18 criteria in 28.7 s | 1.1 min |
| NAV | ≤ 1 h | 162 patients, 17 drafts, 13 TWPAS bundles in 96.5 s | 6.2 min |
| Compile with equivalence | ≤ 20 min | GZQO, 23 criteria, 200 patients in 21.5 s | 0.4 min |

Ingest holds the batch in memory (4.9 GB at 15k); a smaller host ingests in `--since` deltas (D-80). The model share
must be measured on the reference box.

**First hosted-model run** (2026-10-25, `eval/bakeoff/results/2026-10-25/`, open D0 data through the gateway): on
1,015 SIGIR criterion pairs, the two-model rule lost 8 of 79 eligible pairs, equal to the recorded GPT-4 labels, with
false-block UB95 0.016; single models lost 12 to 22. The 4-way accuracy gap to GPT-4 comes from the prompt: TrialBox
says an unmentioned finding is not a negative one. The PHI tripwire refused 103 of 3,045 translated calls (CJK name
false positives).

## 5. The open-data test

`make open-data-e2e` runs the MIMIC-IV FHIR demo (100 ICU patients) through the real path: MIMIC normalisation
(`services/adapter/mapping/mimic/`, table-driven: ICD-9 to ICD-10-CM for the concepts used, 12 lab items to LOINC,
drugs to ATC, ICU procedures to SNOMED CT, dates shifted per patient into the lookback) → adapter `fhir_bulk` → lake →
FEAS for two real trials (EMPULSE NCT04157751, STARRT-AKI NCT02568722). Invariants: the funnel never grows, counts
within 0–100, released counts `<5` or multiples of 5, and a second ingest gives byte-identical results.

Result (2026-10-17): both trials pass every invariant and reproduce. EMPULSE ends at 2 exact (`<5` released);
STARRT-AKI at 2. Mapping coverage: 2,313 ICD-10 converted, 139 ICD-9 cross-walked, 2,054 ICD-9 left unmapped; 26,905 of
107,727 lab events with LOINC. Limits: no notes in the demo, so the judge is not exercised; US codes only; month-end
index dates approximate "current admission"; a 100-patient demo makes most cells small. The test is marked `slow` and
skips without the data. Data and licence: [Data §6](DATA.md#6-open-and-public-data-in-the-tests).

## 6. The Test Bench

`make testbench` (<http://127.0.0.1:8765>) is a developer tool, not a product page: it lives in `tools/testbench/`,
runs only with `TB_ENV` DEV or TEST, loads only D0 or synthetic data, binds to 127.0.0.1, and shows "TEST BENCH:
synthetic and open data only" on every page. A test asserts that no production image contains it. Pages: run end to
end, data platform, trials, feasibility, patients, LLM lab, recall, audit. `make testbench-test` runs its browser
tests.

## 7. The complete-platform run

`tools/complete_run.py` (D-139) runs every stage of plan v4 §5 in one go, ja and zh-TW, and writes a report with a
screenshot per stage. Locally it uses the stub and the 5,000-patient hospital; on the GPU VM it uses the pair and
50,000 patients ([Runbook §11](RUNBOOK.md#11-cloud-runs-owners-ok-first)). The last local report is
`eval/complete_run/2026-11-09-stub-5000/report.md`; the scenario matrix's is below.

**The scenario matrix** (D-141, `tools/scenarios.py`): every way a site gives TrialBox data runs as its own part,
screened, and counted against a recount it did not compute: the database feed (the `hospital` parts), SS-MIX2,
FHIR, the site's Excel and CSV lists, pasted charts, chart files through OCR, REDCap and the built-in forms, an IT
dump with local codes, the offline registry, and three real public datasets (MIMIC-IV demo on FHIR, MedTxt-CR,
TREC CT). The chart scenarios score extraction against the charts' known facts and check that a proposed fact never
excludes before confirmation; every screening scenario lists the model's exclusions against the generator's note
truth (false exclusions must be 0). Known findings of the 2026-11-09 review are reported beside the checks, not
counted. `python -m tools.complete_run --estimate --patients 50000` prints the hours and US$ on the card.

Local proof on the stub, 5,000-patient feed (`eval/complete_run/2026-11-09-matrix-stub-5000/report.md`): 22 parts,
**662 of 662 checks, 84 of 84 screenshots**, about 34 minutes. Every scenario passes: SS-MIX2 and FHIR give the
generator's FEAS recount and the CSV path's funnel; the Excel, Shift_JIS and Big5 lists give each of 100 patients the
generator's state; the pasted and file charts (Word, text PDF, PNG and image-only PDF through the fake OCR) are read
at precision and recall 1.0 by the stub, no proposed fact excludes before confirmation, and after the coordinator
the patient check equals the recount; the IT dump's 200 patients match after mapping; REDCap gets all 50 records and
gives back 16 consent dates; MIMIC, MedTxt and TREC run. Known findings the run reports (not fixed here):

| Id | Where | Seen |
| --- | --- | --- |
| A-01 | gateway probe | a judge call through the installed box's gateway is refused (`step_unconfirmed`) |
| GW-02 | gateway probe | `chart_facts` has no role in `libs/tb_llm/v1_roles.yaml`: chart reading cannot go through the gateway |
| P-04 | SS-MIX2 | 5 of 5 patients whose only cancer is a 疑い diagnosis are excluded by GZQO-EXC-07 |
| FHIR-01 | FHIR | SCREEN scope is 0: the bulk path hashes Practitioner references but keeps Practitioner ids |
| XL-02 | Excel | SCREEN on the hospital's own space after a site list is published spills without bound (stopped at 2 GB) |
| B-03 | REDCap | a longitudinal project linked with no event: 0 of 5 records written ("event name '' is not valid") |
| MAP-01 | IT dump | name suggestions: 胃癌 and 乳癌 to C22.0, 本態性高血圧症 to E78.5 |
| DUMP-01 | IT dump | 2 of 3 patients with an undated cancer row are "ready" |
| B-01 | SS-MIX2 | flagged lab values ("8.2 H", ">8.2") read as unknown, not FALSE, on this path: holds here |

What only the card can show: model exclusions against the note truth (the stub may not exclude), extraction
precision and recall of the real model in ja and zh-TW, real OCR quality, and the gateway path end to end.

## 8. How documents and the build are scored

The yardstick of the reviews (TB-PLAN-03 §9; `docs/reviews/`): five points, one each; 4.5 means five with one minor
residue.

1. Complete against what it claims to be.
2. Zero stale cross-references (`tools/doclint.py`).
3. Every "built" claim names a test, commit or screenshot from the current head.
4. One owner, one status, one change history.
5. A reader in the named role can act without opening another document.

The build is scored on the same scale by the reviews (the design and code review of 2026-11-08 gave 3.3; plan v4
puts steps 0–7 at about 4). The independent re-review after step 9 scores both.
