# R1-COHORT: the cohort-selection set, its criteria in TrialBox's terms, and its metric (2026-11-24)

**Reader:** the people who build TrialBox: lane N, which builds the evaluator (card N-COHORT), the walk, which runs
it on the B200, and the integrator, who rules on the open choices in "Choices for the integrator".

Card R1-COHORT (lane R1, docs only) [#639 7121102791]. The set is the 2018 shared task on cohort selection for
clinical trials, track 1. It is the direct public benchmark for trial screening, and the like-for-like comparison with
published systems. This page gives the set's shape, its 13 criteria mapped to TrialBox's criterion model, the
challenge's own metric as its official script computes it, and the published scores. It holds no data. The set is
under a data use agreement and never enters this repository, CI or GitHub. N-COHORT's tests use a synthetic
three-patient fixture in the same format.

Sources:

- [P] Stubbs et al., JAMIA 2019;26(11):1163-1171, doi:10.1093/jamia/ocz163 (PMC6798568). This is the task's
  overview paper.
- [E] The organisers' track 1 evaluation script, `track1_eval.py`: 307 lines, sha256
  `c50cdd019b079f2ae9cc1b856702ca20054912e5ab94848e7d216c2afafa126f`, read 2026-11-24. Line numbers below refer to
  this file. Its README defines the ranking measure.

## 1 The set

- **Patients and records.** 288 patients with diabetes, each with 2 to 5 longitudinal records (the 2014 heart-disease
  corpus) [P]. Train holds 202 patients with labels; test holds 86, released unlabelled [P].
- **Labels.** "met" or "not met" for every patient and criterion. The annotators used "possibly met" as well; every
  such label was resolved in adjudication, so the gold standard holds only the two values [P].
- **Annotators.** Two medically trained annotators. The mean kappa across criteria was 0.54, from 0.31 for
  MAKES-DECISIONS to 0.73 for ABDOMINAL; KETO-1YR has -0.1 [P]. Per-criterion figures are in section 2.
- **Format.** One xml file per patient. The root has two children, the text and `TAGS`. Each criterion is a child
  element of `TAGS` with a `met` attribute whose value is `met` or `not met` [E lines 46-47].
  - The root element is named `PatientMatching`. This name is seen only in a third-party copy of the DTD and in
    participants' code, not in a primary source. N-COHORT should take the root from the DTD that comes with the data.
- **Time.** "For criteria requiring temporal reasoning, we used the most recent record, regardless of date, as 'now',
  and used previous record dates to determine if the criterion was met" [P].
- **No coded data.** Every answer comes from note text. Labs and medicines are read from notes, so
  the coded path (rules on FHIR resources) has nothing to read unless N-COHORT extracts facts from the notes first.

## 2 The 13 criteria in TrialBox's terms

How to read the table:

- Each criterion becomes one TrialBox criterion of kind `inclusion`. A predicate that is true means "met"; a
  predicate that is false means "not met" (`services/matching/verdict.py:37-44`; met and not met at
  `services/orchestrator/scenarios/case.py:372`). Unknown is the third state; section 3.3 gives how it is scored.
- The IR fields follow `schemas/v4/criterion_ir.schema.json`: `class`, the atom's `domain`, `quantifier`, `value`,
  `window`, and `value_if`/`note_question` where only a note can answer.
- Windows count back from the most recent record (`anchor` index = that record's date), as [P] defines "now".
- The "Kind" column is `tools/public_accuracy/criterion_kinds.json`'s kind; "Answer by" is that file's answer path.
- The definitions are [P]'s, word for word.
- "Kappa" is the annotators' agreement [P]; "n.c." means not confirmed from [P]'s text.

| Criterion | Definition [P] | Kind | TrialBox criterion (IR) | Answer by | Kappa |
|---|---|---|---|---|---|
| DRUG-ABUSE | Drug abuse, current or past | lifestyle | class `note`; condition atom (drug use disorder value set), quantifier `any`, no window; `note_question` "Is there drug abuse, current or past?" | notes, then person | 0.63 |
| ALCOHOL-ABUSE | Current alcohol use over weekly recommended limits | lifestyle | class `note`; `note_question` on current use over weekly limits; structured proxy: alcohol use disorder condition, window -365..0 | notes, then person | 0.59 |
| ENGLISH | Patient must speak English | logistics | class `note`; demographic atom (preferred language) where a record states it; else `note_question` | person | 0.46 |
| MAKES-DECISIONS | Patient must make their own medical decisions | judgement | class `human` in clinical use; for this benchmark class `note` with `note_question` (choice C2) | person, never a model | 0.31 |
| ABDOMINAL | History of intra-abdominal surgery, small or large intestine resection, or small bowel obstruction | procedure_device | class `mixed`: procedure atom (intra-abdominal surgery, bowel resection value sets) OR condition atom (small bowel obstruction), quantifier `any`, no window | rules, then notes | 0.73 |
| MAJOR-DIABETES | Major diabetes-related complication: amputation, kidney damage, skin conditions, retinopathy, nephropathy, neuropathy, as a result of uncontrolled diabetes | diagnosis | class `mixed`: OR of condition atoms (one value set per listed complication), `diagnosis_role` diabetes-related; `note_question` for "result of diabetes" | rules, then notes | 0.62 |
| ADVANCED-CAD | Two or more of: two or more medicines for CAD; history of MI; angina now; ischemia, past or present | diagnosis | class `mixed`: count>= 2 over four atoms (medication atom with count>= 2 over a CAD-treatment value set; MI condition; angina condition, `clinical_status` active; ischemia condition) | rules, then notes | 0.37 |
| MI-6MOS | MI in the past 6 months | temporal | condition atom (MI value set), window -180..0 from the most recent record | rules, then notes | 0.63 |
| KETO-1YR | Diagnosis of ketoacidosis in the past year | temporal | condition atom (diabetic ketoacidosis value set), window -365..0 | rules, then notes | -0.1 |
| DIETSUPP-2MOS | Taken a dietary supplement (excluding vitamin D) in the past 2 months | medication | medication atom (dietary supplements value set minus vitamin D), window -60..0 | rules, then notes | 0.66 |
| ASP-FOR-MI | Use of aspirin to prevent MI | medication | class `mixed`: medication atom (aspirin), `latest` in the most recent record; `note_question` for "to prevent MI" | rules, then notes | 0.62 |
| HBA1C | Any hemoglobin A1c value between 6.5 % and 9.5 % | lab | observation atom on `VS_HBA1C` (`rulesets/GZQO`), quantifier `any`, value `between` 6.5 and 9.5 %, no window | rules | n.c. |
| CREATININE | Serum creatinine > upper limit of normal | lab | observation atom (serum creatinine), quantifier `any`, value with `ref` uln multiple 1 (`RefRange`: the result's own range, else the site table) | rules | n.c. |

Notes on the table:

- **The value sets** for the conditions, procedures and medicines named above are not in the tree, except
  `VS_HBA1C` (`rulesets/GZQO/valuesets/VS_HBA1C.json`). N-COHORT writes them as a ruleset of its own, in the
  ruleset layout (`ir/`, `valuesets/`, `labels.yaml`, `manifest.yaml`).
- **The `between` value.** The tree has no example of a `between` value in a ruleset's IR. HBA1C will be its first.
- **ADVANCED-CAD and MAJOR-DIABETES** are compound. [P] defines both with the lists above, and N-COHORT encodes those
  lists, not a wider clinical reading.
- **"Ever" criteria.** ABDOMINAL and DRUG-ABUSE have no window ("history of", "current or past"). Every record of the
  patient counts.

## 3 The metric

### 3.1 What the script computes [E]

- **Per criterion and value.** For each value v in {met, not met} and each patient, the script pairs (gold = v,
  system = v) (lines 176-180). It counts TP, FP, FN and TN on those pairs (lines 183-192). P = TP/(TP+FP),
  R = TP/(TP+FN) and F1 = 2PR/(P+R), and each is 0.0 when its denominator is 0 (lines 69-102).
- **Per-criterion score.** It is the mean of the criterion's met F1 and not-met F1 (line 231).
- **Overall (micro).** TP, FP, FN and TN are pooled over all 13 criteria, once for met and once for not met
  (lines 183-186, 236-243). The overall micro F1 is (pooled-met F1 + pooled-not-met F1) / 2 (line 247).
- **Overall (macro).** The mean of the 13 per-criterion scores (lines 233, 257).
- **Ranking.** The README says: "The official ranking measure is Overall (micro) F(b=1)". It is the score to report
  and to compare.
- **The paper's own prose.** [P] describes the overall score as an average of per-criterion averages. That reads as
  the script's macro row. The script and its README are the operative definition; R1-COHORT follows them.

### 3.2 What N-COHORT reports

- **Per criterion:** met P/R/F1, not-met P/R/F1, and the criterion's mean F1.
- **Overall:** the micro F1 (the ranking measure) and the macro F1, on the 86 test patients.
- **The same report on the 202 train patients**, labelled as train. Nothing is tuned on test.
- **Counts behind each figure:** TP, FP, FN, TN, and the number of unknowns before mapping (section 3.3).
- **The published reference beside ours,** from section 4.
- **A check of the scorer.** N-COHORT's scorer gives the same figures as [E] on the synthetic fixture, to four
  decimals, with [E] run unchanged. This proves the scorer is like for like.

### 3.3 TrialBox's third state

The challenge has two labels; TrialBox has three. An unknown must become one of the two before [E] can score it.

- **Proposed (choice C1):** unknown scores as "not met", and the count of unknowns per criterion is reported beside
  each figure. The annotators labelled a patient "not met" when the records gave no evidence, so an unknown answer
  fits that label. A second, strict figure, with every unknown scored as wrong, is reported with it, so neither figure
  hides the unknowns.
- **Note answers.** By `services/matching/decision.py:1-25`, a note answer of "not met" counts only when it is final,
  given by a pair of two different models, at or above the confidence threshold, and the run's policy allows it;
  otherwise it reads as unknown. On a set that is all notes, most "not met" answers will arrive as unknowns. The
  mapping above turns them back into "not met", and the unknown count shows how many did.

## 4 Published figures [P]

- **Best:** 0.91 overall micro F1 on the 86 test patients, a rule-based system (Medical University of Graz).
  [P] prints it to two decimals only.
- **Next:** 0.9075 (University of Michigan).
- **All runs:** 47 teams and 109 runs; mean 0.799, median 0.8227, minimum 0.2117.
- **Another figure in the tree.** `docs/research/2026-10_literature_competitors.md:16` gives a 0.9163 "pre-LLM hybrid
  record", from later papers. It is not checked here. N-COHORT's report cites [P]'s 0.91 and names any later figure
  only with its own source and test split.
- **KETO-1YR.** The corpus has no patient who meets it: [P]'s one "met" label was an annotation error. With no gold
  "met" and no system "met", TP = FP = FN = 0, so [E] gives this criterion's met F1 as 0.0. Its mean F1 is then at most
  0.5 for every system, the published ones included. It adds to the pooled not-met counts only. Report it as the
  script gives it; do not drop it.

## 5 Like with like

- **One set, one script, one split.** The comparison with [P]'s systems is fair only on the 86 test patients, with
  [E] unchanged, and with TrialBox's answers mapped by choice C1. A figure on train, on a subset, or with the strict
  mapping is labelled as such, not set beside 0.91.
- **Not R1-L0's metric.** This metric differs from plan 11's one metric, Lind's per-(patient, criterion) agreement:
  the labels, the averaging and the set all differ. Plan 11 section 10's rule holds: a row whose definitions differ is
  "not comparable".
- **R1-L8's validation files.** The figures go there, with the run's bundle, ruleset hash and date. They do not go in
  plan 11, which is frozen.

## 6 Data rules for N-COHORT and the walk

- **The data stays off the repository.** It never enters the repository, CI, GitHub, a log that leaves the B200, or
  a prompt to any paid or cloud service. It is read on the B200 only, from the restricted folder the walk fills.
- **The three-patient fixture is synthetic.** It is written by hand in the same format, with no text taken from the
  set.
- **What may leave the B200:** the report's numbers and counts. No note text, quote, or patient-level row leaves it.
- **Other copies of the set.** Copies of the set appear in public repositories other than the organisers'. They are
  not used, and none is named here.

## 7 Choices for the integrator

- **C1:** unknown scores as "not met" for the official figure, with the strict figure and the unknown counts beside
  it (section 3.3).
- **C2:** ENGLISH and MAKES-DECISIONS. `criterion_kinds.json` answers them by a person ("person, never a model" for
  judgement). The proposal is that on this benchmark only, TrialBox answers them from notes like the others, and the
  report marks them as answered by a path that clinical use does not allow. The other way is to score them as
  unknown, and so as "not met" by C1.

## What this page did not do

- **No run.** The set was not read, and no figure of TrialBox's on it exists yet.
- **Sources not opened.** [P]'s Table 1 counts per criterion, and the kappas for HBA1C and CREATININE, were not read
  in full.
- **Not built.** No value set or ruleset for the 13 criteria. That is N-COHORT's.
