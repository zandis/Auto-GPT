# Launch P2b's compile and its concepts' coverage, read offline, 2026-11-17 (card H-26, plan 8 V4 and V5)

**Reader:** the integrator, lane A2 (the compiler) and lane E (terminology)

This page is plan 8's V4 (a compile report per protocol set) and V5 (a coverage table) for the confirming launch
P2b: run `box-20261117T073759Z-57263236`, on master `57263236` (train 68), 2026-11-17. The run's stored sets are on
branch `integrator/p2b-artefacts`, folder `trialbox/.p2b-artefacts/` (`sigir.tgz` sha256 `1e13cf7a...`, `jmed.tgz`
`6a328376...`, `tcga.tgz` `238229d7...`). That branch is never merged, and nothing from it is copied here beyond the
lines quoted. The data is public: SIGIR 2016 (NCBI TrialGPT) with protocol text from ClinicalTrials.gov,
JMED-Personas (CC BY 4.0) and TCGA-Reports (CC BY 4.0). It holds no hospital data.

The code is lane H's branch `claude/lane-h-26-p2b-compile-and-coverage`, cut from master `3f6a02ec`, which holds
lane A2's #996 (`qualifier_dropped`, train 74) and H-17's #978 (the NHI import and the site lists). No model, GPU or
network was used. The archives were unpacked by the replay's safe extractor into an empty scratch folder outside the
repository. The command:

```
python -m tools.public_accuracy.compile_report sigir.tgz jmed.tgz tcga.tgz --index-day 2026-11-17 --json report.json
```

`tools.public_accuracy.compile_report` is new (this card). It reads each set's `work/answers.json` (the compile as
the run stored it) and `work/raw-traces.json` (the model's stored replies). It also compiles every protocol again
on this commit from those replies, through the compiler's own entry point (`tools.public_accuracy.rerun.recompile`,
card H-4). "report.json" below is that command's report; a field is named as `sets.<set>.<part>.<field>`.

Each finding says whether it is **shown** (read from the run's records or the code) or a **hypothesis**. Nothing on
this page is called met: plan 8 sets no target for V4 or V5 here, and a launch target is met only by a launch
(D-1064 item 4).

## 1. The compile as the run stored it (V4)

**Protocols (shown).** Every protocol of the three sets reached SCREEN: a SCREEN job ran, done or failed
(`sets.<set>.stored`: `reached_screen`, `screened`, `screen_failed`, `failed_before_screen`; from each protocol's
`screen` field in `answers.json`).

| Set | Protocols | Reached SCREEN | Screened | Failed in SCREEN | Failed before SCREEN | Criteria drafted |
| --- | --- | --- | --- | --- | --- | --- |
| sigir | 104 | 104 | 101 | 3 | 0 | 1,165 |
| jmed | 2 | 2 | 2 | 0 | 0 | 4 |
| tcga | 1 | 1 | 1 | 0 | 0 | 1 |
| **all** | **107** | **107** | **104** | **3** | **0** | **1,170** |

- The 3 that failed in SCREEN are the three judging failures H-18 traced (`p2b-review-2026-11-17.md`, section 3):
  NCT00282269, NCT00703417, NCT00974064.
- Each protocol's `approve` is `done`, and `approved_in` is empty on all 107. The record does not say who approved.
  Plan 8's "each rule set approved by a person" cannot be read from it.

**Criteria by kind and class (shown, `sets.<set>.stored.by_kind_class`).**

| Set | Kind | structured | mixed | note | human | All |
| --- | --- | --- | --- | --- | --- | --- |
| sigir | inclusion | 155 | 81 | 33 | 259 | 528 |
| sigir | exclusion | 126 | 212 | 60 | 238 | 636 |
| sigir | documentation | 1 | 0 | 0 | 0 | 1 |
| sigir | **all** | **282** | **293** | **93** | **497** | **1,165** |
| jmed | inclusion and exclusion | 4 | 0 | 0 | 0 | 4 |
| tcga | inclusion | 0 | 1 | 0 | 0 | 1 |

So 497 of sigir's 1,165 criteria (42.7 %) went to a person. jmed and tcga sent none.

**Why each went to a person (shown, `sets.sigir.stored.human_why` and `human_only_reason`).** A criterion counts as
"drafted for a person by the model" when the run's own `ir_extract@4` reply for its line already gave class `human`.
Otherwise its reasons are the compile's flags on it, without the generic `needs_review`. A criterion with several
reasons is counted under each.

| Reason | Criteria with it | With it alone |
| --- | --- | --- |
| drafted for a person by the model | 163 | 163 |
| `logic_invalid` (its coded logic could not be run) | 197 | 53 |
| `structure` (part of a line split or grouped by the structure step) | 174 | 0 |
| `group_member` | 126 | 0 |
| `concept_unmapped` | 60 | 0 |
| `notes_cannot_decide_*` (threshold 37, inferred 28, broad exclusion 22, not in notes 14, negated question 8, negated line 4; the sum of the six) | 113 | 0 |
| `group_heading` | 33 | 0 |
| `alternatives_in_line` | 18 | 0 |
| `stray_field` | 11 | 0 |
| `split_by_model` | 6 | 6 |
| `age_range_exclusion` | 2 | 2 |
| `exclusion_restates_inclusion` | 2 | 2 |
| no flag at all | 2 | 2 |
| 12 other flags, 1 to 7 criteria each | (in `human_why`) | 0 |

- 228 of the 497 have one reason; the other 269 have two or more.
- The largest single cause is the model's own draft (163, 32.8 %). Next is coded logic the compiler could not run
  (197, of which 53 for that reason alone).

**`qualifier_dropped` in the stored drafts (shown).** None. The flag is #996's, merged after P2b's master
(`sets.<set>.stored.qualifier_dropped`: 0, 0, 0).

## 2. #996's rule on the stored extractions, on today's master (V4)

**How (shown).** Each of the 107 protocols was compiled again on `3f6a02ec`. The lines were the ones the run sent to
`ir_extract`, and the model was replaced by the run's stored `ir_extract` and `concept_map` replies. All 107 compiled.
No line needed a reply the run did not store, and no `concept_map` reply was missing
(`sets.<set>.recompiled.status`, `not_rerun` [], `concept_map_replies_not_stored` 0). The CQL translator and the
FHIR server are not run offline. So the recompile's 567 sigir `equivalence_fail` flags mean only that the step did
not run. They are counted apart (`flags_of_steps_not_run`) and not read as findings.

**The count (shown, `sets.<set>.recompiled.qualifier_dropped`).** sigir 4, jmed 0, tcga 0.

| Criterion | Line | Class stored | Class today |
| --- | --- | --- | --- |
| NCT00711399 EXC-04 | "Pregnant women" | structured | human |
| NCT00841789 EXC-06 | "Female subjects diagnosed with KD 12 years of age and older." | human | human |
| NCT00997100 EXC-21 | "Female subject of child-bearing potential who is pregnant or lactating." | mixed | note |
| NCT01227499 EXC-04 | "women with pregnant or lactation" | mixed | note |

- NCT01227499 EXC-04 is the line that excluded sigir-20156 (gold eligible) at S1 in P2b. NCT00997100 EXC-21 excluded
  one of the two "would consider" women (H-18, section 1). Today both go to the notes.
- NCT00841789 EXC-06 was already `human` in the stored draft, so the rule changes its flag, not its class.

**What the rule does not catch (shown).** The stored drafts hold 14 exclusions whose coded logic is an age or a sex
alone, in a class whose logic runs (`sets.sigir.stored.exclusions_demographic_alone`):
- 9 are age-only lines that name nothing more ("Less than 18 years of age"). The rule rightly leaves them alone.
- 5 are sex-only. The rule holds 3 of them (the table above).
- It misses 2:
  - NCT01863628 EXC-06 "in pregnancy and lactation;" stays `structured` with `sex: female` and nothing else.
  - NCT01745731 EXC-14 "Pregnant women or women of childbearing age who do not have adequate contraception." stays
    `mixed`, with the same coded part.

Why they are missed: the rule (`ir_extract.postprocess`, the `named` set) reads only the line's non-demographic
concept candidates. In both stored replies the model drafted "pregnancy", "lactation" and "childbearing age" as
`demographic` candidates (`work/raw-traces.json`, the `ir_extract@4` replies of FEAS jobs `01M7MCRTW71P9PKBK58BXJD2TF`
and `01M7MC8YQ997MQNE9M0HX4SM5Q`). NCT01863628 EXC-06 is the line that excluded the second "would consider" woman in
P2b (H-18, section 1). On today's code it still compiles to "female", alone, as an exclusion that runs at S1. That
it would exclude her again in a second launch is a **hypothesis**: no SCREEN was run here.

**Other class moves (shown; their causes not traced).** Against the stored drafts, 17 criteria change class in the
recompile (`sets.sigir.recompiled.class_moved`). 3 of them are #996's (above). The other 14 are not traced to a
change here:
- structured to human 3, mixed to note 3, mixed to human 3 (these 9 include #996's 3);
- human to mixed 3, mixed to structured 2, structured to mixed 2, human to structured 1.

The recompile's classes: human 501, mixed 289, note 95, structured 280 (`sets.sigir.recompiled.by_class`).

## 3. The concepts' coverage (V5)

**What was measured (shown).** Every concept candidate of every `extract_criteria` call in the three sets' traces,
without the demographic ones, mapped by `Terminology.map` with no model and no synonym dictionary. This is lane E's
measure (D-1116) and the same reading as `tools.terminology_coverage` (it gives the same 1,501 and 204 for sigir).
There are 203 calls (sigir 200, jmed 2, tcga 1, all `ir_extract@4`), 1,732 candidates, and 1,504 not demographic
(`coverage_all`).

**By domain, with what ships in the tree (shown, `coverage_all.by_domain` and `for_review`).**

| Domain | Concepts | Mapped | Of them for review |
| --- | --- | --- | --- |
| condition | 478 | 191 | 91 |
| observation | 598 | 10 | 0 |
| medication | 200 | 4 | 0 |
| procedure | 143 | 0 | 0 |
| encounter | 60 | 0 | 0 |
| claim | 25 | 0 | 0 |
| **all** | **1,504** | **205 (13.6 %)** | **91** |

By set: sigir 204 of 1,501; jmed 1 of 2 ("diabetes mellitus" maps; "hypertension", drafted as an encounter, does
not); tcga 0 of 1 ("invasive breast carcinoma", drafted as an encounter).

**By which table (shown, `coverage_all.by_source`: the mapper's method and the code system of its codes).**

| Answered by | Concepts |
| --- | --- |
| ICD-10-CM, by its own words (TERM-1 step, method `icd10cm`: blocks, descriptions, index) | 147 |
| the curated synonym table, to ICD-10-CM codes (`synonym`) | 44 |
| the shipped LOINC table (`exact` 6, `synonym` 4) | 10 |
| the shipped ATC table (`exact` 3, `synonym` 1) | 4 |
| the shipped NHI tables (`nhi_drug`, `nhi_order`) | 0 |
| a site list | 0 (none is loaded) |
| the NHI open-data extract (H-17, D-1127) | not in the tree: see below |
| **mapped** | **205** |

- **The NHI extract cannot be shown (shown).** D-1127 ships the full NHI lists as
  `services/criteria_compiler/terminology/shipped/`, built by the integrator from the publisher's files. That folder
  is not in the tree on `3f6a02ec`, and the licence register's row `nhi-open-data-full` is still `site-loaded`
  (`docs/licences/register.csv`). So no figure for it exists here.
- What the repository can show is H-17's mechanism. The made-up extract `tests/fixtures/terminology/nhi_*_synthetic.csv`
  was loaded through `tools.terminology_install nhi-drugs` and `nhi-services` into a scratch folder and read with
  `--installed`. It moves 205 to 219: medication 4 to 11, procedure 0 to 7, all 14 for review. Its names were chosen
  to equal words P1b drafted (D-1127). **It is not a coverage figure.**
- **As the compile reads them (shown, `coverage_all.unmapped_refiled_as_condition`).** 21 unmapped candidates are
  diagnoses drafted as a procedure or encounter. The compile refiles such a name to a condition
  (`postprocess.is_diagnosis_name`), and 9 of them map as one. The table counts them in the domain drafted, as lane E
  measured. So the compile itself would map about 214, not 205.

**Beside P1b (shown).** On the same master, P1b's committed concept list maps 266 of 1,273 (20.9 %), the figure
H-17 gave (`python -m tools.terminology_coverage --concepts tests/fixtures/terminology/p1b_concepts.csv`). P2b maps
205 of 1,504 (13.6 %).
- The two launches drafted differently. P1b's sigir traces hold 132 `ir_extract@3` calls; P2b's hold 200
  `ir_extract@4` calls (`integrator/p1b-artefacts`, `sigir.tgz`, `work/raw-traces.json`, attribute `tb.prompt`).
- P2b filed 598 candidates as observations (P1b 308) and 478 as conditions (P1b 588). Many of P2b's unmapped
  observations are conditions or states ("fever", "cough", "pregnancy", "copd", section 3's list).
- That the prompt version moved concepts from condition to observation, and so lowered the share, is a
  **hypothesis**. P1b's sigir held 103 protocols and P2b's 104; whether they are the same trials, and the lines
  sent the same, was not compared here.

**The most frequent unmapped (shown, `coverage_all.top_unmapped`, `--top 20`; ties read from a run with a larger
`--top`).** 1,299 candidates are unmapped: 1,096 distinct names, 967 of which occur once. A name is counted in the
domain drafted ("informed consent" is drafted as a procedure 9 times and as an observation 5 times). Seventeen
names occur 4 times or more, and the next 17 occur 3 times each. All 34 are named, so the twentieth place is not
picked at random:

| Name (domain drafted) | Count |
| --- | --- |
| pregnancy (observation) | 10 |
| informed consent (procedure) | 9 |
| bmi (observation) | 7 |
| fev1, fever, hemoglobin, informed consent, platelet count, serum creatinine, urine cotinine, urine nicotine (observation) | 5 each |
| dialysis (procedure) | 5 |
| lactation (condition) | 4 |
| antibiotics (medication) | 4 |
| body mass index, cough (observation) | 4 each |
| major surgery (procedure) | 4 |
| chronic subdural hematoma (condition) | 3 |
| chemotherapy, heparin, nicorandil (medication) | 3 each |
| ast, bilirubin, copd, creatinine, creatinine clearance, fsh, hematocrit, lactation, smoking status, tsh, wbc (observation) | 3 each |
| airway protocol, mechanical ventilation (procedure) | 3 each |

Reading it:
- The labs (hemoglobin, platelet count, creatinine, AST, bilirubin, TSH, WBC, FEV1) are what LOINC loaded at install
  would answer: it is a named person's licence (TERM-2).
- The drugs (heparin, nicorandil) and classes (antibiotics, chemotherapy) are what the ATC index and the full NHI drug
  list would answer.
- "pregnancy", "lactation", "fever", "cough" and "copd" are conditions or states drafted as observations. A table
  does not fix that: it is a domain question for the compiler (lane A2).
- "informed consent" (14 in all) is no terminology.

## Proposed cards

One line each: the owning lane, what to do, and the evidence. They go through the integrator.

- **Lane A2:** #996's rule should also hold an exclusion whose coded part is a sex alone when the line's qualifiers
  were drafted as `demographic` candidates that are no age or sex ("pregnancy", "lactation", "childbearing age"). It
  could read those candidates, or the line's own words. Evidence: section 2, NCT01863628 EXC-06 and NCT01745731
  EXC-14, FEAS jobs `01M7MCRTW71P9PKBK58BXJD2TF` and `01M7MC8YQ997MQNE9M0HX4SM5Q`.
- **Lane A2:** look at why `ir_extract@4` files conditions and states ("pregnancy", "fever", "cough", "copd") as
  observations, where no table answers them. Evidence: section 3, 598 observations against P1b's 308.
- **Lane H (this tool), with the integrator:** run `compile_report` with `--installed` on the shipped NHI folder once
  the integrator ships it (D-1127), to give the NHI extract's column. Evidence: section 3.
- **Lane G (the driver):** write who approved each rule set (`approved_in` is empty on all 107), so V4's "approved by
  a person" can be read. Evidence: section 1.

## Not shown

- **The NHI extract's coverage.** The shipped folder is not in the tree (section 3).
- **Whether P2b's SCREEN would change** under today's compile. No SCREEN was run. Section 2 shows the compile only.
- **The causes of the 14 other class moves** in the recompile (section 2).
- **Who approved the rule sets.** The record does not say (section 1).
- **Class agreement on chia** (plan 8 V4's second measure). It needs the chia set, not a launch's records.
