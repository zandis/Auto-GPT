# Root review 15: patient finding, the central piece, and every service around it (lane J, job B16, 2026-11-18)

**Reader:** the owner (a clinician) first, then the builders and whoever writes plan 10.

**The owner's words:** "Multicenter trial, single, IIT, registry, reimbursement: they all need to find patients, so
finding patients according to structured or unstructured criteria is the central piece, and all possible services
need to be complete. Search for all possible functionalities."

**Basis.** Master `7da6edd3` (train 80). The stored launch P2b on branch `integrator/p2b-artefacts` at `2bcf5ca9`,
read with `git show`, never merged; its three sets unpacked into an empty scratch folder and read as data. Reviews 05
(the model ladder), 06 (terminology), 07 (validation) and 08 (serving), plan 9 revision 2 (on its branch), and the
measurement pages `docs/plan/measurements/p2b-review-2026-11-17.md` and
`docs/plan/measurements/p2b-compile-and-coverage-2026-11-17.md`. Nothing they measured is measured again here; they
are cited. The sibling review 14 covers multicentre structure and the study life cycle; this review touches those only
where finding depends on them.

**Marks.** Every claim carries one: **[M n]** measured here (entry n of section 13, command and number); **[R
file:line]** read in the repository (paths relative to `trialbox/`); **[S n]** a public source opened for this review
(section 14: link, date, terms); **[O]** opinion. **Not verified** where I could not check. No model was called, no
GPU used, nothing paid for, no hospital data read. "SSI" is taken to be the Japanese vendor Software Service, Inc.;
this is **not confirmed**, and no conclusion below depends on it.

---

## 1. One page for the owner

**What finding is in TrialBox today.** One engine answers one question: "does this patient meet this list of
criteria, as far as the record can say?" It runs in a fixed ladder per patient and criterion: coded data first
(compiled SQL), then a keyword and a meaning search in the notes, then a large model that must quote the note, then a
second model, then a person. Its answers are three-valued (met, not met, unknown), and its first rule is that
**unknown never excludes**. Around this engine the box already has feasibility counts, a weekly pre-screening list,
a re-screen after an amendment, referral lists per department, a one-patient eligibility sheet, NHI reimbursement
lists (switched off for 1.0), cohort counts and a trial-opportunity feed. [R section 2]

**What is good enough today.** [O, on the evidence of sections 2 and 5]
- The safety design is right for pre-screening: an unknown keeps the patient, a single model never excludes, every
  model answer needs a verbatim dated quote, and every look at a chart number goes through one audited path.
- When the box does answer, it is nearly always right. On the 388 SIGIR criterion labels I could align with the
  box's answers, it answered 43 of the 284 that the physicians could answer from the note, and agreed on 42 [M 2].
- Feasibility is a real product: a sequential funnel, unknowns counted per step, threshold what-ifs, monthly
  incidence, a Monte Carlo enrolment curve, small cells rounded before anything leaves the hospital [R section 5].

**What is not good enough.**
1. **The box answers few questions itself.** In the SIGIR launch set it decided 138 of 895 patient-criterion cells
   (15 %): 103 by coded data, 35 by the two models; 372 were left unknown and 385 waited for a person [M 1]. No SIGIR
   patient reached the top tier [M 1]. Part of this is the test data (SIGIR charts are one note, no coded rows), part
   is the engine (sections 2.3 and 3).
2. **The richer criterion model exists only on paper.** Criterion model v3 already describes lines of therapy,
   change from a baseline, doses, k-of-n logic, a "will qualify on" date and a planned-start anchor. The engine
   evaluates none of it; it runs model v1 and uses v3 only to hash [R section 2.1]. Most reimbursement rules in Japan
   and Taiwan need exactly those parts (section 4).
3. **Two silent compile faults on the inclusion side**: a negated inclusion line ("No prior chemotherapy") compiles to
   "has chemotherapy" (2 of 239 coded inclusions; latent until the code lists of review 06 are loaded) [M 4], and a
   mixed inclusion whose coded part is only the age is settled "met" on the age alone, its disease part never asked
   (6 of 81 mixed inclusions) [M 5].
4. **Several services are half-built and then hidden**: the engine computes a watch-list tier and every output turns
   it into "excluded" [R]; the TrialGPT reverse matcher runs only in the test bench [R]; the criterion library is
   built and wired to nothing [R]; reviewers' corrections never become rules [R].
5. **Missing outright**: one patient against all of the site's open studies, event alerts on a new result,
   co-enrolment and burden rules, ranking inside a tier, equity monitoring of who is found, cohort export in
   ATLAS/FHIR form, genomic matching [R section 5].

**The five changes that matter most.** [O]
1. **Make criterion model v3 the one the engine runs** (lines of therapy, baselines, k-of-n, anchors, flip dates),
   compile to it, and retire v1 behind an exact-equivalence test. Cards B16-1 to B16-4.
2. **Fix the two inclusion-side compile faults** before review 06's full code lists turn them live. B16-5, B16-6.
3. **A per-patient view: one patient against every approved study of the site**, used at clinic, admission and tumour
   board, from the same engine. B16-9.
4. **Turn the hidden parts on**: the watch-list with its "re-check on" date, alerts on a new result for watched
   patients, the criterion library, and rules proposed from reviewers' corrections. B16-7, B16-8, B16-12, B16-14.
5. **Measure finding per criterion kind and per rung**, per language and per site, as a release report, and tie it
   to review 07's bound and reader study. B16-16, B16-17.

**What it costs.** 24 cards: S 7, M 11, L 6 (section 9). Nothing here needs a paid run beyond those reviews 07 and 08
already listed; card B16-17 adds no GPU time if it reads the stored traces. [O]

---

## 2. The engine as it is, traced end to end

### 2.1 From criteria in to feedback, step by step

| Step | What happens | Where |
| --- | --- | --- |
| Criteria in: free text | A protocol (PDF, DOCX, XLSX, TXT, MD, CSV) is parsed into inclusion, exclusion, renewal and documentation lines with their section refs | [R `services/orchestrator/scenarios/review.py:1-10`; `services/criteria_compiler/service.py:850-878`] |
| Criteria in: registry record | ClinicalTrials.gov API v2 (live, offline pack or cassette) through `/ctgov/search`; used by COHORT, the opportunity feed and SIGIR | [R `services/criteria_compiler/service.py:412-425`; `services/orchestrator/scenarios/trials.py:1-6`] |
| Criteria in: structured | Approved rulesets as IR files in the repository (`rulesets/RA-BIO/ir/`, eight rulesets shipped); no import of an ATLAS cohort, CQL library or FHIR EvidenceVariable | [R `rulesets/`; M 0 grep] |
| Representation | Criterion IR v1: kind, class (structured, note, human, mixed), boolean logic over atoms (domain, value set, quantifier any/none/count>=/latest/all, value, window from index or event, duration, age, sex, nine derived scores, clinical status), a note question, a human question | [R `schemas/criterion_ir.schema.json:1-118`] |
| The richer model | IR v3 adds line of therapy, change from baseline, windowed aggregates, dose and route, diagnosis role, conditional thresholds, screening and randomisation anchors, organ-function macro, human checklists, `flip_rule`, `filter_class`, `safety_critical`, genomic and specimen domains | [R `libs/tb_contracts/criterion_ir.py:1-14`, `:53-66`, `:382-412`] |
| ...and where it is used | Only to hash a criterion (`upgrade_v1` then `canonical_hash`) and in the library; no evaluator reads a v3 field: `flip_rule`, `event_atom`, `filter_class`, `genomic` appear in no service | [R `services/matching/cascade/engine.py:293-298`; M 0 grep] |
| Compile | Model extraction (`ir_extract@4`) in parts, terminology mapping (06), structure checks (headings, alternatives, groups), demotion of what cannot compile, then **SQL** (the screen) and **CQL/ELM** (CASE and the equivalence gate) from the same IR, an equivalence test, a draft for review | [R `services/criteria_compiler/service.py:887-1003`, `:606-643`] |
| Amendment | Unchanged lines reused with their ids; changed lines keep the replaced id; a re-screen list ("returns", "no longer", "in screening") | [R `services/criteria_compiler/service.py:883-939`; `services/console/studies.py:500-520`] |
| Data each kind reaches | structured: the lake tables by domain; note: note sentences inside the criterion window; human: nobody until a person answers; mixed: coded first, notes when the codes are silent | [R `schemas/criterion_ir.schema.json:16`] |
| S0 scope | An encounter in the lookback; opt-outs removed; contact-denied kept in counts, never listed | [R `services/matching/cascade/engine.py:9-10`] |
| S1 coded | Compiled SQL at every month-end; three-valued; a code outside the readable lists, a proposed fact, a suspected diagnosis (疑い) or no record of the kind gives unknown, never an exclusion | [R `engine.py:535-717`] |
| S2 pre-filter | Approved lexicon terms on the note sentences in the window; no note in the window gives `unknown:data_gap` | [R `engine.py:799-887`] |
| S2b meaning search | Embedding cosine against a threshold; above goes to the judge, below would mean absence; the threshold is a placeholder prior | [R `services/matching/cascade/s2b_semantic.py:1-35`] |
| Absence rule | "Zero hits" may answer only for a criterion certified under CAS-13; the certified list is empty in screening, so every zero-hit pair goes to the judge | [R `engine.py:856`; `services/orchestrator/scenarios/screen_cascade.py:613-615`, `:639`] |
| S3 judge | Prompt `judge@5`: answer only from the excerpts, quote character for character with its date, `unknown` for suspected findings; asked in order of exclusion power per expected token, stopping at the first verified hard "not met" | [R `libs/tb_llm/prompts/judge_v5.md`; `engine.py:1246-1329`] |
| Mapping a judgement | No verified quote, a confidence under 0.75, a note left out by the budget, or an exclusion "present" on a quote that does not state the condition: each becomes unknown | [R `engine.py:1192-1244`, `:190`] |
| S4 verifier | Second model on would-be strong candidates; disagreement becomes unknown | [R `engine.py:1331-1365`] |
| Tri-state and unknowns | Unknown has a kind (`data_gap` or `uncertain`) and a coded reason; an exclusion left unknown keeps the patient; an inclusion left unknown keeps the patient in "review" | [R `engine.py:650-706`, `:1382-1408`] |
| Tiers | strong, potential (uncertain or data gap), **watchlist** (excluded only by time-sensitive criteria), excluded | [R `engine.py:1382-1408`; `services/matching/cascade/model.py:22`] |
| The list | Inside the engine sorted by tier then pseudonym; the console's weekly PI list sorts by next visit, then tier, then pseudonym | [R `engine.py:1422`; `services/console/studies.py:438-440`] |
| Watch-list in outputs | Mapped to "excluded" in every output | [R `services/orchestrator/scenarios/screen_cascade.py:56-63`] |
| Review | PI marks: approach, need information, not suitable now, not now with a re-check date; a reviewer may set criteria at S5 | [R `services/console/studies.py:358-365`, `:438-440`; `engine.py:1443-1446`] |
| Feedback | `FEEDBACK` with outcome enrolled, screen_fail, declined, not_contacted and a free reason code; used to calibrate reach and acceptance rates for the enrolment simulation, not to change any criterion | [R `services/orchestrator/scenarios/feedback.py:1-17`; `services/orchestrator/scenarios/calibration.py:1-10`] |
| Cadence | SCREEN by hand; MICROBATCH weekly for booked patients, new patients and earlier exclusions, and after an ingest for newly booked patients only | [R `services/orchestrator/scenarios/microbatch.py:1-25`] |

### 2.2 What the stored launch shows (only what reviews 06, 07, 08 and the P2b pages did not measure)

Already measured elsewhere and not repeated: criteria by kind and class (1,165 in SIGIR; 497 for a person), the
reasons a criterion went to a person, concept coverage (205 of 1,504 mapped), `concept_map` empties (06), the
eligible-exclusion bound and per-language gaps (07), call counts, token sizes and S2/S2b behaviour on TCGA (08).

**Which rung answered each patient-criterion cell** [M 1]

| Set | Cells | Coded (S1) | Two models (S3/S4) | Unknown | Waiting for a person | Machine-decided |
| --- | --- | --- | --- | --- | --- | --- |
| SIGIR (101 protocols, 102 pairs) | 895 | 103 | 35 | 372 | 385 | 138 (15.4 %) |
| JMED (2 protocols, 594 pairs) | 1,118 | 592 | 0 | 526 | 0 | 592 (53.0 %) |
| TCGA (1 protocol, 500 pairs) | 500 | 0 | 427 | 73 | 0 | 427 (85.4 %) |

Tiers: SIGIR 83 review, 19 excluded, **0 high**; JMED 524 review, 70 excluded, 0 high; TCGA 48 high, 73 review, 379
excluded [M 1].

**The note path in SIGIR** [M 6]: 371 note-criterion slots; 298 pairs reached S2; the lexicon hit in **4** (1.3 %),
6 had no note in the window, 288 had zero hits; S2b sent all 288 on ("above" 288, "below" 0); 291 pairs were judged;
S4 judged 0 pairs. So in SIGIR, as in TCGA (08), neither pre-filter removed a single pair: the judge saw everything
the notes could decide.

**Per-criterion agreement with the physicians' criterion labels (SIGIR gold, 535 labels)** [M 2]. 388 labels align
with a box criterion of the same protocol by text; 147 do not (the box split or merged lines).

| Physicians said | Box: met / not excluded | Box: not met / excluded | Box: unknown | Box: a person | Count |
| --- | --- | --- | --- | --- | --- |
| eligible on this line | 40 | 1 | 124 | 104 | 269 |
| ineligible on this line | 0 | 2 | 11 | 2 | 15 |
| not enough information | 3 | 2 | 61 | 38 | 104 |

- When the box answers a line the physicians could answer, it agrees 42 of 43 times; it answers 43 of 284 (15.1 %).
- The one wrong "not met" is "Male and female" read as a sex atom; the two answers on "not enough information" lines
  that excluded are pregnancy lines compiled to "female" (both known: P2b review, compile page section 2). [R
  `docs/plan/measurements/p2b-compile-and-coverage-2026-11-17.md:84-134`]
- 104 of 269 "eligible on this line" cells waited for a person and 124 stayed unknown. On this data, the dominant
  cost of the engine is not error but abstention. [O]

**Criterion kinds in the 1,165 SIGIR criteria** (a regular-expression classification, English, multi-label; rough,
for proportions only) [M 3]: temporal wording 28.1 %, diagnosis 22.9 %, medication 16.7 %, age or sex 16.1 %,
"no history of" or "history of" 7.9 %, consent and capacity 7.7 %, procedure or device 7.6 %, laboratory value 6.0 %,
pregnancy and contraception 5.4 %, counts and repetition 5.3 %, vital sign or measure 4.7 %, lifestyle 4.0 %, scale or
stage 3.4 %, allergy 2.9 %, imaging 2.7 %, another study 1.7 %, investigator judgement 1.5 %, logistics 1.1 %,
biomarker 0.4 %; 18.0 % matched none. 638 of 1,165 (54.8 %) carry two or more kinds. The per-kind answer rates are in
section 3.

### 2.3 Four findings in the engine itself

1. **A negated inclusion line compiles as presence.** "PRIOR CONCURRENT THERAPY: No prior chemotherapy or
   radiotherapy" (inclusion, structured) compiled to `{"domain": "procedure", "quantifier": "any", "valueset":
   "VS_CHEMOTHERAPY"}`; "No significant cardiopulmonary disease, or other contraindication to EGD" (inclusion, mixed)
   the same way. 2 of 239 coded inclusions [M 4]. The compiler rewrites a negated **exclusion** to its positive form
   [R `services/criteria_compiler/ir_extract/postprocess.py:611-618`] and flags a negated inclusion line only when
   the notes would decide it [R `postprocess.py:371-373`]; nothing checks the coded logic of an inclusion. Both
   carry `concept_unmapped`, so today they answer unknown; once review 06's full code lists load, the first would
   **exclude every patient who never had chemotherapy**, the eligible ones. This is H-01, the harm nobody sees. [O]
2. **A mixed inclusion is settled by its coded fragment.** For a mixed inclusion the codes decide when they say
   "true", and the note question is never asked [R `engine.py:586-590`]. When the model's coded part is only the age,
   the line "passes" on age: 7 of 81 mixed inclusions in SIGIR have an age- or sex-only coded part, and 6 were
   answered "met, coded" ("Age 18 to 75, Performance status WHO 0-2, …", "Children aged 1 to 12 years with acute
   community-acquired pneumonia", "18 years or older with a clinical or genetic diagnosis of FAP", "… presenting with a
   symptomatic chronic subdural hematoma") [M 5]. This lists ineligible patients as meeting a line (H-03, visible to a
   reviewer), and it can make a patient "strong" when nothing else is open. The `qualifier_dropped` rule of #996
   covers exclusions only [R `docs/plan/measurements/p2b-compile-and-coverage-2026-11-17.md:84-123`].
3. **Inside a tier, order says nothing about the patient.** The engine sorts by tier, then pseudonym [R
   `engine.py:1422`]; the console adds next visit first [R `services/console/studies.py:438-440`], which is the right
   first key. Among SIGIR's 83 review pairs the number of open criteria ranges from 1 to 38 (median 7, 23 distinct
   values) [M 7]: a reviewer starting with the fewest open criteria reaches a decision sooner. On SIGIR the signal for
   eligibility itself is weak (median open 6 for eligible, 10 for "would consider", 7 for "not refer"; 38, 33 and 10
   pairs) [M 7]. Rank for the reviewer's effort, not as a probability. [O]
4. **The watch-list is computed and thrown away.** A patient excluded only by time-sensitive criteria gets the tier
   `watchlist` [R `engine.py:1388-1392`]; every output maps it to `excluded` [R `screen_cascade.py:56-63`]. The
   weekly MICROBATCH does re-screen earlier exclusions in full [R `microbatch.py:16-25`], so nobody is lost for good,
   but nobody is told "this patient qualifies on 2027-02-03 when the 90-day washout ends". The IR v3 field for that
   date (`flip_rule`) is evaluated nowhere [R `libs/tb_contracts/criterion_ir.py:367-370`; M 0 grep].

---

## 3. A taxonomy of eligibility criteria, and whether the engine can express and answer each

**What the literature says about the mix.** [S]
- 1,000 random ClinicalTrials.gov criteria: 93 % comprehensible, of these 85 % with significant semantic complexity,
  40 % relying on temporal data (Ross et al. 2010) [S 4].
- Chia: 12,409 criteria from 1,000 phase IV trials, 41,487 entities of 15 types, 25,017 relations; 1,606 criteria
  (12.9 %) "not useful for patient-focused database queries"; 86.8 % evaluable; 65.9 % of domain entities mapped
  strongly to OMOP; about 85 % complex, 35 % with more than one semantic pattern (Kury et al. 2020) [S 2].
- n2c2 2018 track 1: 288 patients' longitudinal notes, criteria chosen to need concept extraction, temporal reasoning
  and inference; best micro-F1 0.91 with a rule-based system; the top ten were rule-based or hybrid (Stubbs et al.
  2019) [S 3].
- Criteria2Query: entity F1 0.795, relation F1 0.805; negation 0.984, logic 0.864, entity normalisation **0.514**,
  attribute normalisation 0.793 (Yuan et al. 2019) [S 5].
- TrialGPT: 87.3 % criterion-level accuracy on 1,015 patient-criterion pairs, retrieval recall over 90 % using under
  6 % of trials, screening time down 42.6 % in a user study (Jin et al. 2024) [S 1].
- RECTIFIER (heart failure trial): structured EHR data could decide **5 of 6 inclusion and 5 of 17 exclusion**
  criteria; on 13 note questions accuracy 97.9 to 100 %; overall sensitivity 92.3 %, specificity 93.9 % against
  90.1 % and 83.6 % for study staff; the authors ask for "final clinician review before patient engagement" (Unlu et
  al. 2024) [S 6].
- TREC Clinical Trials 2021 to 2023: **not verified** (not opened in this session).

**The table.** "Answer by" is the rung that should answer it [O]. "Expresses / answers today" is read from the IR
schema and the engine [R]. "SIGIR share and answered" is from M 3 (rough classification) with the machine-decided
share of that kind's cells.

| Kind | Example | Answer by | Representation needed | Expresses / answers today | SIGIR share; cells answered by machine | Gap |
| --- | --- | --- | --- | --- | --- | --- |
| Age, sex | "Aged 18 to 75" | rules | age at an anchor, sex | yes / yes [R schema `age`, `sex`] | 16.1 %; 100 of 154 | age at a **planned start** (v3 anchor not run); "male and female" read as one sex (P2b) |
| Diagnosis present | "Histologically confirmed …" | codes, then notes | condition + verification + role | yes, with clinical status, suspected flag [R `services/matching/proposed.py:11-13`] | 22.9 %; 20 of 200 | certainty ("histologically confirmed") has no field; diagnosis role (v3) not run |
| Diagnosis attributes | stage, histology, laterality, onset | notes, pathology report | value on a condition; report span | not in v1; v3 has no stage field either | in diagnosis | **no staging or histology atom**; TNM must go to the notes |
| Biomarker, genomic | "EGFR exon 19 deletion", "PD-L1 ≥ 50 %" | structured genomic report, then notes | variant, gene, test, value | v3 domain `genomic` declared, not run [R `criterion_ir.py:65`] | 0.4 %; 0 of 3 | missing L (B16-21) |
| Lab value with window | "Creatinine ≤ 1.5 mg/dL within 28 days" | rules | value, unit, window, latest | yes, with units guarded [R schema `value`, `window`] | 6.0 %; 0 of 46 (SIGIR has no labs) | ×ULN works only in v3 (`ref`), not run |
| Lab trend, change | "creatinine rise ≥ 30 % from baseline" | rules | baseline pick + change | v3 `Change`, not run | in lab | missing (B16-2); needed by Taiwan psoriasis rule (section 4) |
| "Most recent" | "latest HbA1c 7 to 10 %" | rules | quantifier latest | yes [R schema `quantifier`] | – | – |
| Medication current / prior | "on metformin", "prior anti-TNF" | codes, then notes | drug class (ATC), window | yes, but 4 of 200 drug concepts mapped (06) | 16.7 %; 4 of 143 | terminology (06) |
| Washout | "no chemotherapy in the last 4 weeks" | rules | window + flip date | window yes; flip date no | in medication | "qualifies on" date (B16-7) |
| Dose, route, cumulative | "methotrexate ≥ 15 mg/week for 3 months" | rules | dose per period, attainment over time | v3 `Dose`, not run | – | missing (B16-2); every NHI biologic rule needs it |
| Line of therapy | "after ≥ 2 prior lines" | rules + notes + person | regimen, line, setting, progression | v3 `LineOfTherapy`, not run; `lot_rules` id pattern only | – | missing L (B16-3) |
| Procedure, device | "prior CABG", "pacemaker" | codes, then notes | procedure; device implant | yes as procedure; no device domain | 7.6 %; 3 of 73 | device (MRI-incompatible implant, lecanemab rule) |
| Performance status, scales | ECOG, NYHA, Karnofsky, MMSE, CDR, PASI | rules on coded or templated values, then notes | observation value, or derived | nine derived scores (BMI, eGFR ×3, DAS28, BASDAI, ASDAS, CDAI, SDAI) [R schema `derived`] | 3.4 %; 2 of 35 | ECOG/NYHA/MMSE/CDR/PASI/Child-Pugh/MELD have no calculator or extractor (05 card B) |
| Computed from parts | eGFR, Child-Pugh, DAS28 | rules | pinned calculator | yes for nine [R `services/matching/stored_scores.py:1-20`] | – | Child-Pugh, MELD, CHA2DS2-VASc, PASI missing |
| Temporal logic | "within 30 days of", "before/after", "at least twice, ≥ 4 weeks apart", "for ≥ 6 months" | rules | windows, event anchor, repetition with spacing, duration | window, event anchor, count>=, duration yes; **spacing between events no** | 28.1 %; 82 of 253 | "twice ≥ 4 weeks apart" (Taiwan RA rule) cannot be said |
| Counts, sequences | "≥ 2 exacerbations in 12 months" | rules | count in window | yes (`count>=`) | 5.3 %; 2 of 43 | ordered sequences ("A then B") no |
| k of n items | "4 of 6 items, including ① and ②" | rules | at-least combination | **no** (and, or, not only) | – | missing (B16-4); Japan's designated-disease severity needs it |
| Negation, absence | "no history of", "never" | codes for exclusions; notes with care | `none`, `not`, certified absence | yes, but inclusion polarity unchecked (2.3 item 1) | 7.9 %; 4 of 71 | B16-5; absence in notes needs CAS-13 certificates (05) |
| Pregnancy, contraception | "not pregnant, effective contraception" | person at the screening visit; codes for a recorded pregnancy | human checklist + condition | partly; P2b compiled pregnancy to "female" | 5.4 %; 6 of 50 | send to the visit checklist, never to "female" |
| Consent, capacity | "able to give informed consent" | person | human checklist | yes, as human [R postprocess `not_in_notes`] | 7.7 %; 1 of 64 | right as it is |
| Lifestyle | smoking, alcohol | notes, then person | observation; note question | partly | 4.0 %; 1 of 28 | Japanese 喫煙歴 written as "Brinkman index" or "20本/日×30年" (rules) |
| Investigator judgement | "in the investigator's opinion …" | person, never a model | human checklist | yes, as human | 1.5 %; 1 of 11 | must stay human (decision 9) |
| Study logistics | "able to attend visits", "lives within 50 km" | person; address only as a region | human checklist; distance from postcode | human | 1.1 %; 1 of 11 | distance at most as region (privacy) |
| Another study | "no investigational drug within 30 days" | box's own enrolment records, then person | cross-study query | **no** (section 5) | 1.7 %; 1 of 16 | B16-10 |
| Allergy | "hypersensitivity to …" | codes (allergy list), then notes | allergy domain | no allergy domain in v1 | 2.9 %; 1 of 22 | add `allergy` domain (B16-1) |
| Imaging and pathology report | "≥ 5 microbleeds on MRI", "LVEF < 40 % by echo" | report extractor rules, then judge | report span with number | `report` domain in v1, read as notes | 2.7 %; 1 of 26 | numeric extraction from reports (05 card B) |
| Composite and nested | "(A and B) or C, except D" | compile | boolean tree | yes; groups folded only when all members structured [R `service.py:942-951`] | 54.8 % multi-kind | – |
| Site or prescriber, not patient | "specialist in rheumatology", "MRI ≥ 1.5 T available" | configuration | site and user attributes | **no** | – | needed by every Japan/Taiwan reimbursement rule (section 4) |
| Data the chart never has | "willing to travel", "life expectancy > 3 months" | person | human | human | – | right as it is; count them in feasibility as "asked at visit" |

**Reading.** [O] Three things stop more patients from being answered than anything in the model: the missing
representations (dose over time, change from baseline, k-of-n, spacing, line of therapy, site attributes), the
missing extractors for scales and report numbers, and terminology (06). A better model fixes none of them.

---

## 4. One engine for every use, and what each adds

### 4.1 What is common and what each use needs beyond the core

Core, needed by all [O]: the criterion model, the evaluator ladder, the evidence store with quotes, the tri-state
answer with reasons, the audit of every look, small-cell rounding of every count that leaves.

| Use | What "found" means | Adds beyond the core | Exists today | Good is |
| --- | --- | --- | --- | --- |
| Multicentre trial | candidates at this site for a sponsor protocol | the same compiled criteria at every site; per-site terminology; aggregate counts to the sponsor; site comparison (review 14) | FEAS, opportunity feed, COHORT MERGE [R `services/orchestrator/scenarios/cohort.py:1-17`, `opportunity.py:1-12`] | recall |
| Single-centre trial | candidates for the PI | weekly list, referral, re-screen | yes [R section 2.1] | recall |
| Investigator-initiated (IIT, 特定臨床研究) | as above, protocol often in Japanese only | Japanese protocol parsing; jRCT record as input | parse yes; jRCT input **no** (not verified that jRCT offers an API: its site refused this session) | recall |
| Registry enrolment | every patient with the disease, with consent to contact | a population criterion and a consent state; continuing enrolment | ruleset kind `cohort` [R `schemas/ruleset_manifest.schema.json:11`]; consent from the lake [R `cohort.py:6-8`] | recall, then completeness |
| Observational cohort | a phenotype, often retrospective | index date per patient, look-back and follow-up windows, export of the definition | month-end index only [R `engine.py:11-13`] | precision and stated validity (PPV) |
| Post-marketing surveillance (使用成績調査) | every patient started on drug X at this site | trigger on a first prescription; follow-up calendar; link to the EDC | **no** trigger on a first dispense | completeness of capture |
| Reimbursement, Taiwan NHI | patients meeting a 給付規定 item; renewals due; documents missing | dose attainment, spacing, change from baseline, prescriber qualification, documents (photos, X-ray), renewal clock, TWPAS | NAV, TWPAS, SUBMIT; **fenced in 1.0** (decision 8) [R `services/orchestrator/scenarios/nav.py:1-12`] | precision and completeness of documents |
| Reimbursement and use rules, Japan | patients and facilities meeting 最適使用推進ガイドライン; 指定難病 criteria and severity | facility requirements, scale thresholds within a month of start, k-of-n severity, "worst state in 6 months", 18-month review clock | **no** | precision; the physician decides |
| Quality measures, guideline gaps | patients for whom a recommended action is missing | numerator and denominator; exclusions; aggregate trend | the documentation kind and `suggested_order` [R schema `suggested_order`] | both; aggregate |
| Rare disease finding | undiagnosed patients whose record fits a pattern | weak-signal combination, ranking, a person reviews | none beyond notes | recall with a small review load |
| Feasibility before a protocol exists | "how many would a draft criterion set give?" | criteria typed or edited directly, counts at once, what-if | FEAS needs an approved ruleset [R `services/orchestrator/scenarios/feas.py:1-2`] | speed, stated bounds |

### 4.2 Worked examples: Japan

**Example J1: lecanemab, 最適使用推進ガイドライン (revised 令和8年11月)** [S 7], section 4 (投与対象となる患者及び使用施設):
- ① the patient's and family's or carer's intention to be treated, confirmed with the safety content; ② not
  contraindicated: severe hypersensitivity, or before the first dose "血管原性脳浮腫、5 個以上の脳微小出血、脳表ヘモジデリン
  沈着症又は 1 cm を超える脳出血"; ③ MRI (1.5 Tesla or more) possible (no implanted metal device not confirmed
  MR-compatible); ④ "MMSE スコア 22 点以上" and "CDR 全般スコア 0.5 又は 1", confirmed "投与開始前 1 か月以内の期間を目安に";
  ⑤ then amyloid PET or CSF showing Aβ pathology.
- Facility: the first dose and the first six months at a facility meeting conditions on physicians (training in ARIA
  MRI reading), MRI capacity and a team; treatment "原則 18 か月まで", continuation after an assessment.
- What the engine needs [O]: ① human checklist; ② a report-number extractor (count of microbleeds, size of bleed)
  plus a judge, from the radiology report; ③ a device atom and a human check; ④ two scale values (MMSE, CDR, usually
  in notes or a template in Japanese charts) with a window anchored on the **planned start**, not on a month-end;
  ⑤ an observation or report; facility and physician conditions as site attributes; the 18-month clock as a renewal
  criterion. Today: ①, ⑤ yes; ④ only as note questions and anchored on the index date; ②, ③ and the facility not
  expressible [R section 3]. The synthetic trial ruleset `rulesets/AD-MAB/` is the nearest existing set.

**Example J2: ulcerative colitis, 指定難病 告示番号97** [S 8]:
- Diagnosis: "Definite を対象とする": a) and one item of b) and c), with the listed differential diagnoses excluded;
  "Possible（疑診）" is not counted.
- Severity: "中等症以上を対象とする". 重症 = ① stools ≥ 6/day and ② visible blood (+++), plus ③ fever ≥ 37.5 °C or ④ pulse
  ≥ 90/min, "かつ６項目のうち４項目を満たすもの"; ⑤ Hb ≤ 10.0 g/dL; ⑥ ESR ≥ 30 mm/h or CRP ≥ 3.0 mg/dL. After treatment
  starts, severity is "直近６か月間で最も悪い状態を医師が判断する". Patients below the threshold who need continuing costly
  care are also covered ("高額な医療を継続することが必要なもの").
- What the engine needs [O]: an **at-least-k-of-n** node (missing, B16-4); a **worst-in-window** aggregate (v3
  `Aggregate`, not run); stool count and visible blood from notes in Japanese ("排便回数", "血便（++）") as note questions
  or rule extractors; Possible excluded through the suspected flag (exists); the cost route needs claims data
  (domain `claim` exists; amounts not verified); and the physician decides severity, so the box proposes, never
  certifies.

**Also in Japan, not worked here:** 患者申出療養 (patient-proposed care): the patient applies to the state with
documents prepared by a 臨床研究中核病院; review "原則6週間" per the ministry's material as summarised by the search
result — **the rule text itself was not opened** [S 9]. Finding's role there is reverse matching (one patient →
available 患者申出療養 technologies and trials). 高額薬剤 criteria: **not verified**.

### 4.3 Worked examples: Taiwan

**Example T1: RA biologics, NHI 藥品給付規定 8.2.4.2** (section 8, the 865 KB PDF of the current chapter) [S 10]:
- Prescriber: "限內科專科醫師且具有風濕病專科醫師證書者"; prior review; documents: DAS28 after ≥ 6 months of DMARDs, every
  DMARD's kind, dose, duration and side effects, dated photos of joint swelling, X-ray report.
- DAS28 "必須大於5.1", "此項評分需連續二次，其時間相隔至少4週(含)以上".
- DMARD failure: at least two, methotrexate plus one of the listed; adequate = ≥ 6 months with ≥ 2 months at the
  standard target dose (附表十四), or ≥ 3 months with prednisolone 15 mg/day; intolerance at therapeutic dose for 2
  months.
- Response: "DAS28總積分下降程度大於等於(≧)1.2，或 DAS28總積分小於3.2"; re-application every three months after half a
  year; exclusions include latent TB treated under four weeks, infectious arthritis in the last 12 months, an
  indwelling urinary catheter, malignancy unless adequately treated ≥ 10 years ago, multiple sclerosis; tapering
  after two years with DAS28 < 2.6 for more than six months.
- Against the synthetic `rulesets/RA-BIO/` [R its IR files]: the second DAS28 is approximated as "another DAS28 > 5.1
  between 90 and 180 days before" (INC-06), not "two assessments ≥ 4 weeks apart"; the DMARD rule is "≥ 6 months
  continuous" without the dose attainment; the response rule (REN-02) is class `note` because a decrease from
  baseline cannot be written in v1. Each of these is a v3 part that exists and is not run (B16-2).

**Example T2: psoriasis biologics, NHI 8.2.4.6.1** [S 10]:
- "PASI ≧10" (or ≥ 10 % body surface) for at least 6 months; failure of phototherapy given "每週至少2次" with dose
  records and of at least two systemic agents for ≥ 3 months at stated doses (methotrexate 15 mg/week, cyclosporin
  2.5 to 5 mg/kg/d, acitretin 0.3 to 1 mg/kg/d); defined "cannot use" states (liver biopsy grade, renal function);
  courses of six months, re-application "應於期滿前1個月提出"; PASI25 at week 12 or 16; return to cyclosporin
  unless "Creatinine 基礎值上升≧30%".
- Needs [O]: weight-based dose attainment over time, phototherapy session frequency (procedure count per week), a
  score (PASI) the chart may hold only in dermatology notes, change from baseline, a renewal clock with a lead time.

**Common to all four examples** [O]: dose and frequency over time, change from a baseline, k-of-n, spacing between
two measurements, a planned-start anchor, site and prescriber attributes, documents as criteria, renewal clocks. A
reimbursement module built on today's v1 engine would send most of each rule to a person.

---

## 5. Every service around the finding

Market and project evidence for what such products offer (claims quoted as claims): TriNetX LIVE: "Identify the
patients best-matched to your study", "Assess the feasibility of your study's eligibility criteria", NLP facts "make
clinical detail queryable" [S 11]; Deep 6 AI, as described in secondary sources: NLP over notes, pathology and lab
reports, a cohort builder, "real-time EMR querying", site feasibility, "a trial recommender for physicians"; vendor or
press figures, unverified [S 12]; Epic Best Practice Advisories for research: a "silent" in-basket message to study
staff or a "passive" notice to the treating clinician when a patient meets built-in criteria, after IRB approval
(institutional pages) [S 13]; the HL7 CodeX draft IG defines `ResearchStudy/$match` with an mCODE patient bundle,
zip code and travel radius as inputs (draft 0.1.0) [S 14]; FHIR R5 EvidenceVariable can express characteristics
with `exclude`, `timeFromEvent`, `instances`, `duration` and combinations "all-of | any-of | at-least | at-most"
(maturity 1, trial use) [S 15]; OHDSI CohortDiagnostics gives inclusion-rule attrition, orphan codes, incidence,
index-event breakdown, overlap, patient profiles (Apache-2.0) [S 16]. Review 03 covered ATLAS/Circe, Criteria2Query,
TrialGPT, MatchMiner, Leaf and the vendors it lists; not repeated.

Status: **have**, **partial**, **missing**, **should not have** (in 1.0). Size as cards: S a day or less, M a few
days, L a week or more.

| Service | Status | Evidence | What is missing | Size |
| --- | --- | --- | --- | --- |
| Feasibility counts | have | funnel, monthly new, Monte Carlo, rounding [R `services/orchestrator/scenarios/feas_compute.py:1-10`; `feas_profile.py:1-20`] | note criteria counted as unknown only; no sampled estimate of the note share (CAS-8 sampling exists in the cascade) [R `engine.py:22`] | M |
| "Why so few": attrition | partial | sequential funnel, unknown per step [R `feas_compute.py:300-312`] | each criterion alone and "unknown because no data" vs "fails" shown side by side; orphan codes (CohortDiagnostics does) | S |
| Relaxation what-if | partial | numeric threshold variants, unknown-as-pass variant [R `feas_compute.py:162-210`]; pack section "Criterion impact and relaxation (on request)" [R `services/deliverables/pack.py:58`] | drop a criterion, widen a window, change a list, from the console | M |
| Feasibility before a protocol | missing | FEAS needs an approved ruleset [R `feas.py:1-2`] | a draft criterion set counted without approval, labelled draft | M |
| Reverse matching: one patient → all open studies | partial | CASE: one patient vs one ruleset [R `services/orchestrator/scenarios/case.py:1-20`]; the TrialGPT port only in the bench [R `services/matching/registry_match/pipeline.py:1-10`; used by `tools/trialgpt_compare.py` and `tools/testbench/` only] | one patient against every approved study of the site, from the stored answers | M |
| …at the point of care, admission, tumour board | missing | no ADT trigger; an EMR launch link is planned [R `services/console/reveal.py:1-8`] | a patient panel and a tumour-board list (next week's cases × open studies) | M |
| Real-time alert on a new result or diagnosis | partial | after-ingest run for newly booked patients; weekly re-check [R `microbatch.py:1-25`] | event on a watched patient's new result → re-evaluate that pair → notify | M |
| Watch-list, "will qualify when…" | partial | engine tier [R `engine.py:1392`] dropped in outputs [R `screen_cascade.py:61`]; PI "Not now, re-check on <date>" by hand [R `services/console/studies.py:438-440`] | computed flip date from windows and washouts; the list shows it | M |
| Competing-study conflict, burden | missing | a free-text list of competing trials in the site profile [R `services/console/home.py:702-712`] | patient-level: on another study's candidate list, consented, or enrolled; visit-burden rule | M |
| Ranking by likelihood of eligibility | partial | next visit, tier, pseudonym [R `studies.py:438-440`] | fewest open criteria within a tier [M 7] | S |
| Ranking by likelihood of consent | should not have | – | predicts who says yes from who said yes before: an equity risk and a nudge to skip patients [O] | – |
| Duplicate and already-enrolled suppression | partial | candidate statuses per study [R `services/orchestrator/candidates.py:27-35`] | across studies (with the conflict rule) | S |
| Washout and timing calendar | partial | windows in criteria | per-patient calendar of dates when criteria flip | M (with watch-list) |
| Referral from other departments | have | referral workbooks per department [R `services/orchestrator/scenarios/screen.py:842-891`] | – | – |
| Referral from outside clinics | partial | CASE with an uploaded chart [R `case.py:12-20`] | an intake form and a referral record | S |
| Clinician one-tap response | have | approach, need info, not suitable, not now [R `studies.py:358-365`] | – | – |
| Outreach and scheduling | missing | – | in Japan and Taiwan the treating doctor approaches; a "suggest at next visit" note to the doctor is enough [O] | S |
| Pre-screening log, screen-failure reasons | partial | screening log with reveal [R `reveal.py:1-8`]; feedback with free reason code [R `feedback.py:17`] | a coded reason list (sponsor logs need categories) | S |
| Explanations with quotes and chart links | partial | verbatim dated quote verified [R `engine.py:1192-1244`] | link into the EMR at that note (planned) | M |
| Uncertainty display | partial | tiers, unknown kinds, reasons, confidence floor [R `engine.py:1382-1408`] | per-criterion "why unknown" in plain words on the list; "what would resolve it" exists in CASE only [R `case.py:5-11`] | S |
| Reviewer feedback learning | missing | S5 overrides stored per patient [R `engine.py:1443-1446`]; feedback calibrates rates only | overrides aggregated per criterion into a **proposed rule or lexicon change**, approved by a person, versioned; never silent model drift | M |
| Criterion library and reuse | partial | library tables, repository, Chia seed [R `services/criteria_compiler/library/repository.py:1-20`] | wired to nothing outside its own package [M 0 grep] | M |
| Versioning, re-screen what changed | have | incremental compile, re-screen list [R section 2.1] | re-judging only changed criteria (the judged-pair store helps) | – |
| Equity monitoring of who is found | missing | no code [M 0 grep] | found vs in scope by age band, sex, department, language of notes; aggregate | S |
| Audit of every look at a chart | have | one reveal path, break-glass [R `reveal.py:1-12`] | – | – |
| Patient-facing self-referral | should not have (1.0) | – | public form leads to identity and consent handling the box is not built for [O] | – |
| Registry and biobank links | missing | – | registry enrolment as a study type (review 14); biobank sample availability as a criterion source | L |
| Genomic and biomarker matching | missing | v3 domain declared [R `criterion_ir.py:65`] | variant atoms, a structured report input, OncoKB-style levels (licence to check) | L |
| Imaging and pathology report mining | partial | `report` domain; TCGA pathology judged by notes [M 1] | numeric extractors (microbleed count, LVEF, tumour size) | M |
| Natural-language cohort questions | partial | "Ask" with exact grammar and intent classification [R `services/channels/grammar.py`; 05 section 2f] | free questions compiled to the same IR, shown as criteria before counting | M |
| Export of a cohort definition | partial | CQL and ELM per ruleset [R `service.py:606-643`] | OHDSI ATLAS/Circe JSON, FHIR EvidenceVariable or Group | M |
| Saved searches, subscriptions | partial | rulesets are saved searches; COHORT quarterly | subscribe a person to "new candidate" for a study | S (with alerts) |
| APIs for other systems | partial | `/api/v1` for the patient page [R `reveal.py:4-6`] | a read API for counts and lists; `$match` style for reverse matching | M |
| Multi-site aggregate counts | have | COHORT MERGE, opportunity feed [R `cohort.py:9-11`; `services/opportunity_hub/dashboard.py:1-8`] | review 14 | – |

---

## 6. Accuracy and safety of finding as a product property

### 6.1 What "good" is, per use

| Use | Error that hurts | Primary measure | Secondary | Unknown means |
| --- | --- | --- | --- | --- |
| Pre-screening for a trial or registry | an eligible patient excluded (invisible) | eligible-exclusion bound per language (07 section 3.1) | open share; reviewer minutes per candidate | keep, ask |
| Feasibility | a count off by a factor | count with a lower bound (definite) and an upper bound (definite + unknown); the unknown-as-pass variant already gives the upper [R `feas_compute.py:311-312`] | agreement with a manual count on a sample | widens the interval |
| Reimbursement, use rules | a listed patient who does not qualify (a claim refused, or a drug given outside the rule) | precision of "documents complete"; each missing document named | recall of renewals due | "missing", never "eligible" |
| Quality gap | false gap (a clinician chased for nothing) | precision | recall | not counted as a gap |
| Rare disease | review load | review load per true case | recall on known cases | keep |

[O] One engine, several thresholds: the safety rule "unknown never excludes" holds everywhere; what changes per use is
which list a patient lands on and what the screen calls it.

### 6.2 How a person stays the decider [R, O]

- Already true: a single model never excludes; a disagreement is unknown; investigator-judgement, consent and
  logistics lines are human; the PI's marks set aside, never "not eligible" [R `studies.py:358-365`].
- To add: the inclusion polarity check (B16-5); the mixed-fragment rule (B16-6); reimbursement output worded as
  "items met / items missing", with a physician's sign-off before any document leaves (already the SUBMIT rule [R
  `services/orchestrator/scenarios/submit.py:1-12`]); a "proposed rule" from feedback that a person approves.

### 6.3 How the product proves it per site and per language (ties to 07)

07's cards hold: the bound per language (B7-5), frozen sets (B7-6, B7-7), clinician gold (B7-8, B7-9), the per-class
report and open share (B7-10), the reader study (B7-11). This review adds two things [O]:
1. **Report by criterion kind and by rung**, not only by class: the table of M 1 and M 3 per set, per language,
   per site, every release (B16-16). A kind that the box never answers (lab values on SIGIR, 0 of 46) is visible.
2. **Site acceptance in shadow mode per study**: the first study at a site runs with the coordinator's own manual
   pre-screening beside it for a fixed number of weeks; every patient the coordinator found and the box did not is a
   recall finding, traced to its rung (B16-17). This is the only way to see H-01 at a real site.

### 6.4 Failure modes specific to Japanese and Traditional Chinese charts

| Failure | Where it bites | What the box does today | Mark |
| --- | --- | --- | --- |
| 疑い病名 (suspected) recorded as a diagnosis | coded diagnosis matches | SS-MIX2 疑い flag and FHIR provisional give unknown, never met [R `services/matching/proposed.py:11-13`] | R |
| 保険病名 / レセプト病名: a diagnosis entered to justify a test or drug, not a real diagnosis | coded diagnosis "met" falsely; exclusions fire falsely ("history of malignancy" from a tumour-marker claim name) | nothing distinguishes it | O; prevalence not verified |
| Negation in Japanese: なし, 認めず, (−), 否定的; and the opposite, "否定できない" (cannot be ruled out) | note judgement | the judge prompt asks for `unknown` on "cannot be ruled out" [R `libs/tb_llm/prompts/judge_v5.md`]; the inferred-quote rule knows 否定, 疑 [R `services/matching/inferred.py:106-110`] | R |
| Chinese negation: 無, 否認, 未見, "r/o" | note judgement, polarity rule | polarity markers include 無, 沒有, 未 [R `services/criteria_compiler/ir_extract/polarity.py:20-22`]; 否認 and 未見 not in that list | R |
| English keywords never hit a Japanese note | S2 | D-983 per-patient note language; 32 translated terms (05) | R |
| Taiwan notes: English text under Chinese headings, Chinese drug names | language choice | read by script counts [R `services/matching/notelang.py:1-9`] | R |
| Era and ROC dates (令和5年3月1日, R5.3.1, 民國112年, 1120315) | windows | one parser, refuses what it cannot read for certain [R `libs/tb_common/dates.py:1-20`] | R |
| Full-width digits and units (１．５ｍｇ／ｄＬ) | lab values from notes | not checked in this review | not verified |
| Scales written as free text ("PS 1", "NYHA II度", "MMSE 23/30") | performance status, MMSE | judge only; no rule extractor (05 card B) | R |
| Templates (テンプレート) holding structured values inside a note | everything | not visible as structure unless the connector maps it | O; needs the hospital's sample (section 11) |
| Family history (母: 乳癌) read as the patient's | exclusions | inferred-quote rule lists 家族, 母, 父 … [R `inferred.py:106`] | R |
| Brand names in katakana, YJ and HOT codes for drugs | medication criteria | 06 | R (06) |

---

## 7. The target design on one page

**Criterion model.** One model: IR v3, made live. A criterion is a tree over atoms; atoms are of five families [O]:
1. *Patient facts* by domain (condition with role and certainty; observation with value, unit, ×ULN; medication with
   dose, route, attainment over time; procedure; **device**; **allergy**; report span with a number; genomic variant;
   line of therapy).
2. *Derived values* from pinned calculators (the nine, plus ECOG/NYHA from text rules, Child-Pugh, MELD, PASI).
3. *Time*: windows from index, event, **planned start**, screening, randomisation; spacing between events; duration;
   worst/best in window; change from baseline; a computed **flip date**.
4. *Combinations*: and, or, not, **at least k of n**, with "including ①".
5. *Non-patient atoms*: site and prescriber attributes, documents to attach, and human checklist items with who and
   when (prescreen call, screening visit).

**The ladder per kind.** [O]

| Kind | 1 rules | 2 terminology | 3 rule extractor on text | 4 meaning search | 5 judge + verifier | 6 person |
| --- | --- | --- | --- | --- | --- | --- |
| age, sex, coded lab, coded drug, coded diagnosis | decides | maps | – | – | – | unknowns |
| scales, report numbers | decides if coded | – | decides when it finds a match; else passes on | routes | decides | disagreements |
| diagnosis or history in notes | – | lexicon | – | routes | decides | disagreements |
| absence ("no history of") | coded exclusions | – | – | certified absence only (CAS-13) | inclusions only with a quote | always for inclusions without a certificate |
| consent, capacity, judgement, logistics, pregnancy plans | – | – | – | – | **never** | decides |
| site, prescriber, documents | configuration | – | – | – | – | confirms |

**Services as modules on one core.** Core: criterion store (the library, keyed by canonical hash), evaluator
(S0 to S5), answer store (patient × criterion × version → status, reason, rung, quote, flip date), evidence store,
event intake (new result, new diagnosis, new booking). Modules read the answer store; none re-implements matching:
Feasibility; Pre-screening list and watch-list; Patient view (reverse matching); Alerts; Referral; Co-enrolment
rules; Reimbursement and use rules (1.1, fenced); Registry and cohort; Quality gap; Export and API; Learning (proposed
rules from overrides).

**The order to build.** [O] What waits for what:
1. Correctness first: B16-5 (inclusion polarity), B16-6 (mixed fragment). Nothing waits.
2. The answer store (B16-11) and the per-kind report (B16-16): every module reads the first, every change is
   measured by the second.
3. IR v3 live in steps: anchors and flip dates (B16-1), dose/change/aggregate (B16-2), k-of-n (B16-4), line of
   therapy (B16-3). The watch-list (B16-7) waits for flip dates.
4. The patient view (B16-9) and alerts (B16-8) wait for the answer store.
5. Library (B16-12), learning (B16-14), export (B16-15), equity (B16-13), conflicts (B16-10).
6. Reimbursement and use rules (B16-18, B16-19), registry and PMS triggers (B16-20) in 1.1; genomic (B16-21) after.

---

## 8. Gap table

| What the product does today | What is needed | Evidence |
| --- | --- | --- |
| Runs IR v1; v3 only hashed | v3 evaluated, v1 retired behind an equivalence test | [R `engine.py:293-298`; schema] |
| Negated inclusion compiles to presence | polarity check on coded inclusions | [M 4] |
| Mixed inclusion settled by an age fragment | a coded part must cover the line's concepts, or the notes still decide | [M 5; R `engine.py:586-590`] |
| Machine decides 15 % of SIGIR cells | per-kind extractors and representations (section 3); measured per kind | [M 1, M 3] |
| Watch-list computed, output as excluded | shown, with a flip date | [R `screen_cascade.py:61`] |
| Reverse matcher only in the bench | patient view on the answer store | [R `pipeline.py:1-10`] |
| Library wired to nothing | compile looks up, reuses and records each criterion | [M 0 grep] |
| Feedback tunes rates only | proposed rules from overrides | [R `feedback.py`, `calibration.py`] |
| No co-enrolment rule | cross-study candidate and enrolment check | [R `home.py:702-712`] |
| No equity view | found vs in scope by band | [M 0 grep] |
| No ATLAS/FHIR export | Circe JSON and EvidenceVariable export | [R `service.py:606-643`; S 15] |
| Reimbursement on v1, fenced | v3 parts; site attributes; documents; per Japan and Taiwan rule | [S 7, S 8, S 10; R `rulesets/RA-BIO/`] |
| Release report by class | by kind and by rung, per language and site | [M 1] |
| Validation on public sets only | shadow mode at the first site | 07; [O] |

---

## 9. Cards (to paste into plan 10)

Lanes as in plan 8 section 8b and plan 9 rev 2 (A2 compiler and engine, C2a console, E connectors and terminology, H
validation, D devops, J documents). Ids are this review's.

| Card | What | Size | Lane | Waits for | Proved by |
| --- | --- | --- | --- | --- | --- |
| B16-1 | IR v3 anchors live: planned start, screening, event pick; device and allergy domains; `flip_rule` computed for windows and washouts | L | A2 | – | a fixture where a 28-day washout gives the right flip date; v1 rulesets give byte-identical answers |
| B16-2 | IR v3 dose (per period, attainment), change from baseline, worst/best in window evaluated in SQL and CQL alike | L | A2 | B16-1 | RA-BIO REN-02 compiles as structured; the equivalence gate passes on the Taiwan psoriasis creatinine rule |
| B16-3 | Line of therapy from regimens with a person's confirmation; `lot_rules` versioned | L | A2, E | B16-2 | ten synthetic oncology histories, lines agree with a clinician's |
| B16-4 | At-least-k-of-n and "including" nodes | M | A2 | – | the UC severity rule (4 of 6 including ①②, ③ or ④) on twelve synthetic cases |
| B16-5 | Polarity check on coded inclusions: a negated line with presence logic is rewritten or held, never run | S | A2 | – | the two P2b lines held; a property test over negation words in en, ja, zh-TW |
| B16-6 | Mixed fragment rule: a mixed inclusion whose coded atoms do not cover the line's named concepts keeps its note question even when the codes say true | S | A2 | – | the six P2b lines go to the notes; no other SIGIR verdict changes |
| B16-7 | Watch-list in every output: tier, flip date, "re-check on"; MICROBATCH re-evaluates on the date | M | A2, C2a | B16-1 | a patient appears on the list the day the washout ends |
| B16-8 | Event alerts: a new result or diagnosis for a watched or review patient re-evaluates that pair and notifies the subscriber | M | A2, D | B16-11 | an ingest with one new creatinine flips one pair and sends one notice, audited |
| B16-9 | Patient view: one patient against every approved study of the site, from stored answers; clinic, admission and tumour-board lists | M | C2a | B16-11 | the console walk: a patient page lists three studies with their open criteria |
| B16-10 | Co-enrolment and burden rules: on another study's list, consented or enrolled; per-site rule set by the IRB's policy | M | A2, C2a | owner decision 7 | a fixture patient enrolled in study A is flagged on study B's list without study A's name to unauthorised roles |
| B16-11 | Answer store: patient × criterion × ruleset version → status, reason, rung, quote, date, flip date; erasable with the patient | M | A2 | – | erasure test; MICROBATCH and CASE read it |
| B16-12 | Criterion library wired: compile looks up by canonical hash, reuses an approved criterion, records use | M | A2 | B16-1 | a second protocol with a shared line reuses the approved criterion |
| B16-13 | Equity view: found vs in scope by age band, sex, department, note language; rounded | S | C2a, H | – | the FEAS report carries it; small cells suppressed |
| B16-14 | Learning from overrides: reviewer S5 decisions aggregated per criterion into proposed lexicon or rule changes, approved by a person, versioned | M | A2, C2a | B16-11 | three planted overrides produce one proposal; nothing changes until approved |
| B16-15 | Export a ruleset as OHDSI Circe JSON and FHIR EvidenceVariable; import Circe JSON as a draft | M | A2, E | B16-1 | round trip on the eight shipped rulesets; ATLAS opens the export (not verified offline) |
| B16-16 | Release report by criterion kind and rung, per language and site (M 1 and M 3 as a tool) | S | H | – | the report on the stored P2b sets equals this review's tables |
| B16-17 | Shadow mode at the first site: the coordinator's manual pre-screen beside the box for the first study; each miss traced to a rung | M | H, owner | B16-16, 07 B7-5 | a dry run on the synthetic hospital with a planted manual list |
| B16-18 | Japan use rules: the lecanemab 最適使用推進ガイドライン and one 指定難病 (UC) as synthetic rulesets with site attributes and documents | L | A2, J | B16-2, B16-4, decision 6 | both rulesets compile with no human line except ①-type checks |
| B16-19 | Taiwan NHI: RA-BIO and a psoriasis ruleset rewritten to the real 8.2.4.2 and 8.2.4.6.1 structure | M | A2 | B16-2 | each item of the rule text maps to a criterion; review by a rheumatologist and a dermatologist |
| B16-20 | Triggers for registry and post-marketing surveillance: first dispense of drug X, first diagnosis of Y | M | A2, E | B16-8 | a synthetic first prescription creates a candidate on the PMS study |
| B16-21 | Genomic atoms from a structured report (variant, gene, test), with a licence check of any knowledge base | L | E, A2 | B16-1 | five synthetic NGS reports answer three biomarker criteria |
| B16-22 | Rule extractors for scales and report numbers in three languages (ECOG/PS, NYHA, MMSE, CDR, PASI, LVEF, microbleed count), answering with a quote like the judge | M | A2 | – | a fixture of 60 sentences per language; the judge is asked only where no rule matched |
| B16-23 | Ranking inside a tier by fewest open criteria (after next visit) | S | C2a | – | the weekly list orders review patients by open count |
| B16-24 | Coded screen-failure reasons (a fixed list in three languages) in the screening log and FEEDBACK | S | C2a | – | a sponsor log exports with categories |

Count: **S 7, M 11, L 6** (24 cards).

---

## 10. Decisions only the owner can make

| # | Decision | Options | Recommendation |
| --- | --- | --- | --- |
| 1 | Make IR v3 the engine's model | (a) yes, in steps behind an equivalence test; (b) keep v1 and bolt on | **(a)**: every reimbursement and oncology rule needs it, and the contract is already written |
| 2 | Order inside a list | (a) next visit, then fewest open criteria; (b) a model's eligibility probability | **(a)**: transparent, no calibration needed; (b) waits for 07's reliability tables |
| 3 | Rank by likelihood of consent | allow / forbid | **Forbid** in 1.0: it trains the list to skip people who were approached less often |
| 4 | Patient view at the point of care in 1.0 | console panel only / EMR alert too | **Console panel only**; an EMR alert needs each hospital's IRB and EMR team |
| 5 | Show the watch-list and flip dates to coordinators | yes / no | **Yes** |
| 6 | Japan's use rules (最適使用推進ガイドライン, 指定難病) in the Reimbursement module | with Taiwan's in 1.1 / separately | **With Taiwan's in 1.1**, under decision 8's fence; output "items met / missing", the physician decides |
| 7 | Co-enrolment visibility across studies | show study names / show "in another study" only / none | **"In another study" only**, with the PI able to ask; names to roles the delegation log allows |
| 8 | Equity view | aggregate in FEAS and per study / none | **Aggregate**, rounded; it is the only way to see that notes in one language are read worse |
| 9 | Investigator-judgement, consent, logistics lines | always a person / may be asked of a model | **Always a person** |
| 10 | Patient self-referral | out of 1.0 / in | **Out** |

---

## 11. What the owner or the first hospital must supply

Exact items; synthetic content only; nothing hospital-internal is to be quoted in the repository.

1. The first three to five studies the first site (a general hospital in Japan) intends to run: their jRCT or ClinicalTrials.gov numbers, so their
   criteria (Japanese and English) become the first frozen protocol set.
2. From the HIS vendor (SSI, not confirmed): a **synthetic** export in the real format of: diagnoses with the 疑い flag
   and how 保険病名 are marked (if at all); prescriptions with dose and days; lab results with units; radiology and
   pathology reports; template-structured notes (テンプレート) for MMSE, CDR, ECOG/PS, NYHA.
3. A one-page list of where each common scale lives at the hospital (structured field, template, free text).
4. The hospital's current pre-screening log form and its screen-failure reason list.
5. The IRB's rule on co-enrolment and on contacting patients identified from records (for decisions 4 and 7).
6. Which drugs under 最適使用推進ガイドライン and which 指定難病 the hospital manages most (for B16-18).
7. A clinician reader for ja and one for zh-TW (ruled yes) for B16-18, B16-19 and the shadow-mode traces.
8. A coordinator's time for shadow mode on the first study (B16-17): the manual list of patients they found.

---

## 12. What this document did not verify

- TREC Clinical Trials 2021 to 2023 overviews: not opened.
- jRCT: the site returned 403; whether it offers an API or download is not verified.
- 患者申出療養: only a search result summarising ministry material ("原則6週間"); the rule text was not opened.
- 高額薬剤 criteria in Japan: not opened.
- The NHI section 8 PDF's version date: the NHI listing page refused this session (403); the file opened is the
  865 KB, 62-page section 8 that the search result describes as the 115.9.22 version; the version date is not
  verified from the file itself.
- Vendor claims (TriNetX, Deep 6 AI, Epic) are their own or secondary sources' words; none was tested.
- The prevalence of 保険病名 in Japanese coded diagnoses and its effect on matching: not measured.
- Full-width digit and unit handling in note values: not checked.
- The criterion-kind classification of M 3 is a regular-expression heuristic in English; its shares are rough.
- 147 of 535 SIGIR gold labels did not align with a box criterion by text; M 2 covers the 388 that did.
- SIGIR charts carry no coded rows (its provenance file says so), so its coded share understates what a hospital
  chart allows; no hospital-shaped run was re-read here.
- Whether ATLAS reads an exported Circe JSON offline (B16-15): not tried.
- "SSI" as Software Service, Inc.: not confirmed.

---

## 13. Measurement log

Scripts in `/var/tmp/trialbox-0/b16/scripts/` (not committed); data: `git show
origin/integrator/p2b-artefacts:trialbox/.p2b-artefacts/{sigir,tcga,jmed}.tgz` at `2bcf5ca9`, unpacked into
`/var/tmp/trialbox-0/b16/art/`, read with `python3 -I`.

| # | Command | Number |
| --- | --- | --- |
| 0 | `grep -rliE` over `services` and `libs` (`*.py`, tests excluded) for `flip_rule`, `event_atom`, `filter_class`, `genomic`, `CriterionLibrary`, `registry_match`, `equity\|fairness\|disparit` | `flip_rule`, `event_atom`, `filter_class`, `genomic`: only `libs/tb_contracts/criterion_ir.py`; `CriterionLibrary`: only its own package; `registry_match` outside its package: `tools/trialgpt_compare.py`, `tools/testbench/*`; equity words: 0 files |
| 1 | `survey.py */work/answers.json` (verdict × basis; tiers) | SIGIR: 895 cells, coded 103, pair/notes 35, unknown 372, person 385; tiers review 83, excluded 19. JMED: 1,118 cells, coded 592, unknown 526; review 524, excluded 70. TCGA: 500, pair 48 + notes 379, unknown 73; high 48, review 73, excluded 379 |
| 2 | `agree.py sigir` (gold `built/gold/criteria.jsonl` vs box verdicts, aligned by protocol and normalised text) | 535 labels, 388 aligned; gold pass 269 → box pass 40, fail 1, unknown 124, person 104; gold fail 15 → fail 2, unknown 11, person 2; gold unknown 104 → pass 3, fail 2, unknown 61, person 38 |
| 3 | `taxo.py sigir/work/answers.json` (19 regex kinds, multi-label) | 1,165 criteria; shares as in section 2.2; 638 with ≥ 2 kinds; per kind class and verdict counts as in section 3 |
| 4 | `polarity.py` (coded inclusions whose text is a negation and whose non-demographic atoms ask presence) | 239 coded inclusions; 2 negated lines; 2 with presence logic (NCT00002897 INC-03, NCT00256529 INC-03) |
| 5 | `dropped.py` and an inline count of mixed inclusions with age/sex-only atoms | 575 coded criteria, 127 age/sex-only, 11 naming more; mixed inclusions 81, age/sex-only 7, settled "pass, coded" 6 |
| 6 | sum of `cascade.metrics` over `sigir/work/screen/*.json` | note_criteria 371; S2 hit 4, no notes 6, zero hit 288; S2b above 288, below 0; S3 judged 291; S4 0 |
| 7 | open (unknown + person) criteria per review pair; and by gold pair label | SIGIR 83 pairs: median 7, 1 to 38, 23 distinct; eligible 38 pairs median 6, would consider 33 median 10, not refer 10 median 7 |
| 8 | `pdftotext -layout` on the three source PDFs (sha256 prefixes `93701e37` lecanemab, `1e5650aa` UC, `395c0256` NHI section 8) | 753, 145 and 2,275 lines; quotes in section 4 are from these texts |

---

## 14. Sources opened (2026-11-18)

| # | Source | Terms |
| --- | --- | --- |
| 1 | Jin Q et al. Matching patients to clinical trials with large language models. Nat Commun 2024;15:9074, doi 10.1038/s41467-024-53081-z (PubMed 39557832, abstract) | CC BY 4.0 (journal) |
| 2 | Kury F et al. Chia, a large annotated corpus of clinical trial eligibility criteria. Sci Data 2020;7:281, doi 10.1038/s41597-020-00620-0 (PMC7452886, full text) | CC BY 4.0; the data on figshare under its own licence (the box's Chia seed checks it: `services/criteria_compiler/library/__init__.py`) |
| 3 | Stubbs A et al. Cohort selection for clinical trials: n2c2 2018 shared task track 1. JAMIA 2019;26:1163, doi 10.1093/jamia/ocz163 (PubMed 31562516, abstract) | publisher terms; the data under the n2c2 data use agreement |
| 4 | Ross J, Tu S, Carini S, Sim I. Analysis of eligibility criteria complexity in clinical trials. Summit Transl Bioinform 2010:46-50 (PubMed 21347148, abstract) | PMC open access |
| 5 | Yuan C et al. Criteria2Query. JAMIA 2019;26:294, doi 10.1093/jamia/ocy178 (PubMed 30753493, abstract) | publisher terms |
| 6 | Unlu O et al. Retrieval-augmented generation-enabled GPT-4 for clinical trial screening. NEJM AI 2024;1(7), doi 10.1056/AIoa2400181 (PubMed 42932487), and its preprint doi 10.1101/2024.02.08.24302376 (abstracts) | publisher terms |
| 7 | 厚生労働省・PMDA 最適使用推進ガイドライン レカネマブ（令和５年１２月、令和８年１１月改訂）, https://www.pmda.go.jp/files/000283505.pdf, listed at https://www.pmda.go.jp/review-services/drug-reviews/review-information/p-drugs/0028.html | Japanese government publication; quoted for review |
| 8 | 厚生労働省 指定難病 告示番号97 潰瘍性大腸炎 概要・診断基準等, https://www.mhlw.go.jp/content/10905000/001173518.pdf, listed at https://www.mhlw.go.jp/stf/newpage_53881.html | as 7 |
| 9 | Search result summarising ministry material on 患者申出療養 (e.g. https://www.mhlw.go.jp/moushideryouyou/pdf/moushideryouyou.pdf); the document itself not opened | – |
| 10 | 衛生福利部中央健康保險署 藥品給付規定 第8節 免疫製劑, https://www.nhi.gov.tw/ch/dl-55682-0edce502618d4d309195db2577c9319b-1.pdf (8.2.4.2, 8.2.4.6.1) | Taiwan government publication |
| 11 | TriNetX LIVE, https://trinetx.com/solutions/live-platform/ | vendor page; claims only |
| 12 | Deep 6 AI as described by https://blogs.nvidia.com/blog/deep-6-ai-clinical-trials and https://intuitionlabs.ai/software/pdfs/deep-6-ai.pdf (search summary) | secondary; unverified |
| 13 | Epic BPA recruitment, institutional pages: https://cctr.vcu.edu/support/study-participation-and-recruitment/recruit/epic-best-practice-advisory-bpa-recruitment-tool/ and OHSU's slides (search summary) | institutional pages |
| 14 | HL7 CodeX draft IG "Integrated Trial Matching for Cancer Patients and Providers", https://build.fhir.org/ig/standardhealth/fsh-pct (search summary of its pages) | HL7 continuous build, CC0 for FHIR artefacts (HL7 terms) |
| 15 | FHIR R5 EvidenceVariable, https://hl7.org/fhir/R5/evidencevariable.html (first 100,000 characters read) | HL7 FHIR licence (CC0) |
| 16 | OHDSI CohortDiagnostics, https://ohdsi.github.io/CohortDiagnostics/ | Apache-2.0 |

---

## Change history

- 2026-11-18: first version (lane J, job B16).
