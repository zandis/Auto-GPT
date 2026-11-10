# TB-DS-21 Synthetic hospital generator

| Field | Value |
| --- | --- |
| Document | TB-DS-21 Synthetic hospital generator (specification) |
| Version | 1.3 |
| Date | 2026-11-07 |
| Owner | Aimedics; built by Claude in build step 1 |
| Status | Build specification (TB-REV-006f F6-02). Requirements FR-SYN-01..04 in TB-DS-01 (version per TB-DS-00R; added in v0.10). Living build document: it changes with the generator code. |
| Approval | The owner's merge of the PR that changes this file and the generator together. No separate sign-off. |
| Plan | `SIMPLE-PLAN.md` step 1; `20-build-map.md` |

## 1. Purpose

Every build step is tested on a synthetic hospital, never on real patients. The plan promises a hospital of up to **500,000 patients** with **Japanese-style and Taiwanese-style records** and **clinical notes in Japanese, Traditional Chinese and English**, with known answers. This page says what the generator makes and how.

## 2. What exists today (master `a1e55fa`)

| Piece | What it does | Limit |
| --- | --- | --- |
| `tools/synth/generator.py` (909 lines), `tools/make_fixtures.py` | Deterministic HIS-like tables (patient, encounter, diagnosis, lab, drug, procedure, exam, note, practitioner, registry, appointment) with planted per-patient states and truth files (`note_truth.json`, `human_truth.json`, `needles.json`, `states.json`). Every structured criterion of the GZQO and RA-BIO rulesets has true / false / null cases. Writes CSV and a `cgrd.sqlite`. | Default 600 + 520 patients; Taiwanese names and **zh-TW notes only** (`tools/synth/notes.py`, 11 templates); no Japanese identifiers, no 和暦, no SS-MIX2 layout; no planted PHI spans. |
| `tools/hospital_sim.py`, `eval/hospital_sim/` | Runs the real pipeline on generated hospitals of growing size; measured at 2,000 / 10,000 / 25,000 / 50,000 patients. | Structured scale only; notes are the same zh-TW templates. |
| `tools/synthea_ad_cohort.py` | Applies the coded part of an early-AD protocol to a Synthea CSV export, Python and DuckDB counts must agree. | English US-style Synthea data; Synthea output is not stored in the repo. |
| TB-DS-04 §3.4 | Describes a 5,000-patient Japanese fixture (kanji/kana names, SS-MIX2 layout, 和暦 in 10 % of notes, 保険病名, planted findings and PHI). | Text only; no code. |

Decision: **extend `tools/synth`** into `tools/synth_hospital` rather than start again. It already has the right shape (deterministic, planted truth, the landing tables the ingest reads). Synthea is optional for a larger structured base (§4).

## 3. Parameters

```
python -m tools.synth_hospital \
  --sites jp-head:JP:300000,cgmh:TW:200000 \   # site:style:patients
  --lang-mix JP=ja:0.9,en:0.1 TW=zh-TW:0.9,en:0.1 \
  --studies GOUT-COH,RA-BIO,RA-COH,GZQO \
  --ref-date 2026-11-01 --years 8 --seed 42 \
  --out /var/tmp/synth --profile full|ci
```

- `--profile ci`: 5,000 patients, one site per style; **target** under 5 minutes in CI (FR-SYN-04), not yet measured — the step-1 PR measures it and writes the result here.
- `--profile full`: up to 500,000 patients in total; one night on the demo VM (FR-SYN-04).
- Same seed → byte-identical output.

### 3.1 Rates (prevalence parameters)

All rates live in one file, `tools/synth/rates.yaml`, keyed by study and criterion, so a test can read the same numbers the generator used. The values below are the ones in `generator.py` today (patient mix in `run()`, per-criterion `pick()` weights); the step-1 PR moves them into the YAML unchanged and adds the cohort studies.

**Patient mix per site:** gout 30 %, RA 26 %, oncology 4 %, general 40 %.

| Study | Criterion (ruleset ID) | Planted states and rates | Source of truth |
| --- | --- | --- | --- |
| GZQO | Gout diagnosis | coded 0.90, uncoded 0.10 | `states.json` `gout_dx` |
| GZQO | BMI band | <24 0.12, 24–25 0.08, 25–27 0.15, 27–30 0.22, >30 0.25, missing 0.08, stale 0.05, no height 0.05 | `states.json` `bmi` |
| GZQO | Serum urate | good 0.60, bad 0.25, missing 0.10, stale 0.05 | `states.json` `urate` |
| GZQO | Creatinine / eGFR | normal 0.75, low 0.15, missing 0.10 | `states.json` `creatinine` |
| GZQO | HbA1c | good 0.60, bad 0.15, missing 0.25 | `states.json` `hba1c` |
| GZQO | ALT | good 0.70, bad 0.12, missing 0.18 | `states.json` `alt` |
| GZQO | Systolic BP | good 0.65, bad 0.15, missing 0.20 | `states.json` `sbp` |
| GZQO | GZQO-INC-06 urate-lowering therapy | long 0.40, short 0.12, gappy-ok 0.12, gappy-bad 0.10, none 0.18, old 0.08 | `states.json` `ult` |
| GZQO | GZQO-INC-05 two or more flares in 12 months (note) | positive 0.45, negative single 0.15, negative none 0.15, absent 0.25 | `note_truth.json` |
| GZQO | GZQO-EXC-11 current flare (note) | positive 0.12, negated 0.40, absent 0.48 | `note_truth.json` |
| GZQO | GZQO-INC-07 willing to inject (human) | willing 0.50, unwilling 0.15, no information 0.35 | `human_truth.json` |
| GZQO, RA-BIO | Shared exclusions | T1DM 0.06; pancreatitis acute 0.04, chronic 0.03; MTC 0.02, MEN2 0.02; GLP-1 recent 0.08, old 0.06; bariatric 0.04; malignancy recent 0.05, old 0.04, skin 0.03; MI/stroke recent 0.05, old 0.05; pregnancy (women) dx 0.12, hCG+ 0.08, hCG− 0.30 | `states.json` |
| RA-BIO | RA diagnosis | long 0.80, recent 0.12, none 0.08 | `states.json` `ra_dx` |
| RA-BIO | RA-BIO-REN-02 response to prior biologic (note) | good 0.40, poor 0.20, absent 0.40 | `note_truth.json` |
| RA-COH, GOUT-COH | Cohort entry criteria | Reuse the RA and gout states above; no extra states (cohort rulesets have no note criteria). | `states.json` |
| All | PHI spans in notes | Proposed (none are planted today): 3 spans per note on average (name 1.0, date 1.0, chart number 0.4, phone 0.2, address 0.2, insurer number 0.1, hospital name 0.1); at least 1 span in 70 % of notes | `gold/notes.jsonl` `phi` |
| All | Retrieval needles | 20 fixed needle sentences; each patient note has a 0.06 chance of carrying the next one; the rest are placed at the end of the run | `needles.json` |

Expected eligible rate is not a parameter: it falls out of the independent states. The step-1 PR prints it per study in the run summary, and `e2e_simple` checks the funnel against the truth files, not against a fixed number.

## 4. Structured records

- **Tables:** the landing tables of `tools/synth/generator.py` (`TABLES`), unchanged, so the ingest and all tests keep working.
- **Japanese style (JP sites):** kanji and kana names (family + given, from frequency lists), 8-digit chart numbers, insurer numbers in the right format but never a real one, 保険病名 alongside ICD-10, JLAC10 lab codes and YJ drug codes, dates as 西暦 in tables and 和暦 (令和/平成) in 10 % of notes. (An SS-MIX2-style folder layout as a second writer is hospital stage, H: nothing in the build reads it, since FR-ING-03 is H.)
- **Taiwanese style (TW sites):** as today (CGRD-like tables, ICD-10-CM, NHI drug codes), names from `notes.py`.
- **Name lists:** see §4.1.
- **Appointments:** each patient has a next-visit table with clinic days per department, so the PI list (N1) can be sent on clinic days.
- **Scale:** the generator writes in chunks of 10,000 patients per site to keep memory flat.
- **Synthea (optional):** for a larger, epidemiologically shaped structured base, run Synthea (Apache-2.0) and map its CSV into the landing tables, then apply the JP/TW layer above (names, codes, dates, appointments). Synthea has no Japanese module, so the layer is always TrialBox's own.

### 4.1 Name lists and other identifiers

| List | Source | Licence / note |
| --- | --- | --- |
| Taiwanese surnames and given-name characters | `tools/synth/notes.py` `SURNAMES`, `GIVEN` (written by hand in the repo) | Own list; names are random three-character combinations, so any match to a real person is chance. |
| Japanese family names (kanji + kana) | New file `tools/synth/names_ja.py`, written by hand from common surnames | Own list; frequency ranks are facts, no third-party dataset is copied. |
| Japanese given names (kanji + kana) | Same file, split by sex | Own list, as above. |
| English names | Same approach, `names_en.py` | Own list. |
| Hospital, department and street names | Invented names only (for example 「さくら総合病院」); never a real hospital | Own list. |
| Chart, insurer and phone numbers | Generated in the right format; checked against the reserved-pattern list in §6 | No real number list is used. |

No list is downloaded at run time, so the generator runs offline.

## 5. Notes, planted findings and PHI

- **Templates per language:** JA, zh-TW and EN progress notes, outpatient notes, imaging reports and discharge summaries. Each template mixes filler sentences with **finding slots**.
- **Planted findings:** for each study criterion that needs notes (for example "current gout flare", "MMSE ≥ 22", "amyloid PET positive", "study partner available"), the generator plants positive, negative, negated ("no flare") and absent cases at fixed rates, sometimes years old, sometimes in a different note type.
- **Planted PHI spans:** names, chart numbers, phone numbers, addresses, insurer numbers, dates and hospital names, written into notes the way they appear in real text (in signatures, in "family member X called", in referral letters). Every span is recorded.
- **Gold file** (`gold/notes.jsonl`, one line per note):

```json
{"note_no": "n000123", "mrn": "J00012345", "lang": "ja",
 "findings": [{"criterion": "GZQO.INC-03", "value": "yes", "start": 120, "end": 141}],
 "phi": [{"type": "name", "start": 5, "end": 9}, {"type": "phone", "start": 210, "end": 222}]}
```

- **Offsets** (`start`, `end`) are Unicode code points (Python `str` indices) into the note text as written, end exclusive; not bytes. This matters for Japanese and Chinese text.
- The early-Alzheimer study in the build is `AD-MAB` (synthetic, scenario J1, T-503), screened on the `jp-ad` site with its `NEUR-COH` memory-clinic registry. `GZQO` is the gout study, not an Alzheimer's study.
- The PHI gold feeds the N-07 leak check; the findings gold feeds the SCREEN recall check.

### 5.1 Finding-slot catalogue

A finding slot is a place in a template where a sentence for one criterion goes. Each slot has four sentence sets per language: positive, negative, negated and absent (absent means no sentence; the note is filler only).

| Ruleset criterion | Slot | Note types | Positive example (zh-TW today) | Negated example |
| --- | --- | --- | --- | --- |
| GZQO-INC-05 | `flare_history` | progress, outpatient | `N.flare_sentence` (date + joint) | `N.no_flare_sentence` |
| GZQO-INC-05 (negative) | `flare_single` | progress | `N.single_flare_sentence` | — |
| GZQO-EXC-11 | `flare_current` | outpatient | `N.current_flare_sentence` | `N.no_current_flare_sentence` |
| GZQO-INC-07 | `injection_willing` | outpatient | `N.injection_willing_sentence(True)` | `N.injection_willing_sentence(False)` |
| RA-BIO-REN-02 | `biologic_response` | progress | good response sentence | poor response sentence |
| Retrieval needles | `needle` | progress | the 20 fixed sentences in `needle_queue` | — |

Step 1 adds the JA and EN sentence sets for every row and the date forms (西暦, 和暦, ROC year in zh-TW). A new note criterion in a ruleset needs one new row here and its sentence sets; the check in §6 fails if a ruleset note criterion has no slot.

### 5.2 Truth files

All truth files are written next to the tables, one set per site.

| File | Shape | Key | Values |
| --- | --- | --- | --- |
| `states.json` | `{mrn: {attribute: state}}` | chart number, then the attribute names of §3.1 (`bmi`, `urate`, `ult`, `pregnancy`, …) plus internal flags such as `igra_done`, `hbv_result` | the state strings of §3.1 |
| `note_truth.json` | `{mrn: {criterion_id: value}}` | chart number, then ruleset criterion ID (`GZQO-INC-05`) | `yes`, `no`, `unknown` |
| `human_truth.json` | `{mrn: {criterion_id: value}}` | as above, for criteria only a person can answer | `willing`, `unwilling`, `no_info` (GZQO-INC-07) |
| `needles.json` | list of `{mrn, query, fragment, note_no}` | `note_no` | the retrieval query and the planted sentence |
| `gold/notes.jsonl` | one object per note (§5) | `note_no` | findings with offsets, PHI spans with offsets |

```json
{"states": {"10000123": {"gout_dx": "coded", "bmi": "27-30", "ult": "gappy_ok"}},
 "note_truth": {"10000123": {"GZQO-INC-05": "yes", "GZQO-EXC-11": "unknown"}},
 "human_truth": {"10000123": {"GZQO-INC-07": "willing"}}}
```

(The three files are shown in one object for brevity; each is its own file.)

## 6. Checks

- Same seed gives the same output (hash of every file).
- Every planted finding and PHI span is found again at its offsets in the written note.
- Every structured criterion of every listed ruleset has true, false and (where allowed) null cases.
- No generated name, phone or insurer number matches a reserved real pattern list.
- Every note criterion in a listed ruleset has a slot in §5.1.
- The observed rate of each state in §3.1 is within ±2 percentage points of its parameter on the full profile (±5 on `--profile ci`).

## 7. Not in scope

Real patient data; images; genomic data; free-text in languages other than JA, zh-TW and EN.

## 8. References

| Ref | Document |
| --- | --- |
| [Y1] | TB-DS-01 SRS v0.10, FR-SYN-01..04 |
| [Y2] | TB-DS-04 Verification and operations, §3.4 end-to-end tests, N-07 |
| [Y3] | TB-DS-07 Data dictionary (landing tables) |
| [Y4] | `20-build-map.md`, step 1 |
| [Y5] | Synthea, Apache-2.0 (optional structured base) |

## Change history

| Seq | Version | Date | Author | Change |
| --- | --- | --- | --- | --- |
| 1 | 1.0 | 2026-11-07 | Claude for Aimedics | First issue from TB-REV-006f F6-02. |
| 2 | 1.1 | 2026-11-07 | Claude for Aimedics | TB-REV-006f §R N7-09: GZQO instead of the non-existent AD-EARLY; SS-MIX2 second writer tagged H; gold offsets are Unicode code points; CI time is a target measured in step 1. |
| 3 | 1.2 | 2026-11-07 | Claude for Aimedics | TB-REV-006g: §3.1 rates (values taken from `generator.py`), §4.1 name-list sources, §5.1 finding-slot catalogue, §5.2 truth-file schema, two new checks in §6, References §8, approval row, Seq column. |
| 4 | 1.3 | 2026-11-07 | Claude for Aimedics | TB-REV-006g §F F-02: Status row cites TB-DS-01 "version per TB-DS-00R". |
